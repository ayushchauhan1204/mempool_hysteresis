"""Discrete-event blockchain network simulator.

Models, per node: a mempool, the set of transactions it has seen, a block tree
with longest-chain fork choice, and the set of transactions confirmed on its
active chain. Transactions spread by gossip; blocks are mined on a Poisson
schedule by hash share; reorgs return transactions to the mempool.

Residue mechanisms (each a modelling choice, each parameterised):
  * a reconnected peer receives the chain (headers-first sync) but not the
    mempool, matching Bitcoin Core's default (no BIP35 service by default);
  * transactions returned to the mempool by a reorg are not re-announced
    unless ``relay_reorged`` is set;
  * a miner can only include transactions it holds.

Transport model:
  * ``transport="tcp"``: packet loss adds TCP retransmission delay (exponential
    backoff) instead of losing the message; a blackholed direction buffers
    messages and delivers them after the link heals plus a residual backoff.
  * ``transport="lossy"``: loss and blackholes drop messages outright.
  * ``outage_mode="reset"``: partitions and isolations break connections;
    in-flight and queued messages are lost and peers reconnect afterwards.
  * ``outage_mode="buffered"``: those outages behave like TCP blackholes.

The ground-truth evaluator (``_evaluate``) reads true state every
``eval_interval`` seconds. Nothing it computes is visible to policies.

Extension C (off unless ``cfg.mempool_cap`` is set): bounded mempools with
fee-rate eviction, a rolling minimum fee rate and a recently-rejected memory
(rule in results/extensions/EXTENSIONS.md), plus an evicted-divergence series
next to the unchanged residue. With the default (None) nothing changes.
"""
from __future__ import annotations

import heapq
import itertools
import math
from collections import deque

import numpy as np

from .config import SimConfig
from .scenario import Scenario, u01

OK, SLOW, FAIL = 0, 1, 2


class Block:
    __slots__ = ("id", "parent", "height", "miner", "txs", "time")

    def __init__(self, bid, parent, height, miner, txs, time):
        self.id = bid
        self.parent = parent
        self.height = height
        self.miner = miner
        self.txs = txs
        self.time = time


class Simulation:
    def __init__(self, scn: Scenario, policy_factory, cutoffs=None, keep_series=True):
        self.scn = scn
        self.cfg = cfg = scn.cfg
        self.seed = scn.seed
        n = cfg.n_nodes
        self.n = n
        self.peers = scn.peers
        self.edges = scn.edges
        self.lat = scn.lat
        self.created = scn.created.tolist()
        self.origin = scn.origin.tolist()
        self.fee = scn.fee.tolist()
        self.t_end = scn.t_end
        self.cutoffs = list(cutoffs) if cutoffs else [scn.t_end]
        self.keep_series = keep_series

        # event queue
        self._heap = []
        self._seq = itertools.count()
        self.now = 0.0

        # node state
        self.mempool = [dict() for _ in range(n)]   # tx -> local entry time
        self.seen = [dict() for _ in range(n)]      # tx -> first time this node learned it
        self.known = [{0} for _ in range(n)]        # block ids
        self.tip = [0] * n
        self.chain = [[0] for _ in range(n)]        # active chain, index = height
        self.conf = [set() for _ in range(n)]       # txs confirmed on active chain
        self.orphans = [dict() for _ in range(n)]
        self.blocks = [Block(0, -1, 0, -1, (), 0.0)]

        # link state
        self.mult = [[1.0] * n for _ in range(n)]
        self.loss = [[0.0] * n for _ in range(n)]
        self.down = [[False] * n for _ in range(n)]
        self.blackhole = [[False] * n for _ in range(n)]
        self.bh_since = {}
        self.epoch = [[0] * n for _ in range(n)]
        self.buffer = {}
        self.outage_edges = []

        # counters
        self.c = dict(lost=0, dup_tx_msgs=0, dup_block_msgs=0, tx_msgs=0, block_msgs=0,
                      mined=0, reorgs=0, reorg_returned=0, buffered=0)

        # Extension C (off unless cfg.mempool_cap is set): bounded mempools with fee-rate eviction
        self.cap = cfg.mempool_cap
        if self.cap is not None:
            self.min_fee = [0.0] * n                    # rolling minimum fee rate per node (never decays)
            self.dropped = [dict() for _ in range(n)]   # tx -> (time, "evicted" | "rejected"), per node
            self._fee_heap = [[] for _ in range(n)]     # (fee, tx) per node, stale entries skipped lazily
            self.c.update(evicted=0, rejected=0, refused_deliveries=0)

        # monitor state (one entry per undirected edge)
        self.edge_index = {e: k for k, e in enumerate(self.edges)}
        self.m_window = [deque(maxlen=cfg.ping_window) for _ in self.edges]
        self.m_healthy = [True] * len(self.edges)
        self.m_okstreak = [0] * len(self.edges)
        self.m_last = [OK] * len(self.edges)
        self.m_unhealthy = 0
        self.m_round = 0
        self.monitor_log = []

        # evaluator series
        self.series = {k: [] for k in ("t", "U", "D", "B", "chain_ok", "n_tips", "pend")}
        for c_ in self.cutoffs:
            self.series[f"res@{c_:g}"] = []
        if self.cap is not None:
            for k in ("lost", "max_mp", "n_full"):
                self.series[k] = []
            for c_ in self.cutoffs:
                self.series[f"evdiv@{c_:g}"] = []
                self.series[f"gres@{c_:g}"] = []

        self.policy = policy_factory(self)

    # ------------------------------------------------------------------ events
    def at(self, t, fn, *args):
        heapq.heappush(self._heap, (t, next(self._seq), fn, args))

    def run(self):
        cfg = self.cfg
        order = np.argsort(self.scn.created, kind="stable").tolist()
        self._arrival_order = order
        if order:
            self.at(self.created[order[0]], self._tx_arrival, 0)
        if len(self.scn.block_times):
            self.at(float(self.scn.block_times[0]), self._mine, 0)
        d = self.scn.disturbance
        if d.kind is not None:
            self.at(d.start, self._dist_start)
            self.at(d.end, self._dist_end)
        self.at(cfg.ping_interval, self._ping_round)
        self.at(cfg.eval_start, self._evaluate)
        self.policy.on_start()

        heap = self._heap
        pop = heapq.heappop
        horizon = cfg.horizon
        while heap:
            t, _, fn, args = heap[0]
            if t > horizon:
                break
            pop(heap)
            self.now = t
            fn(*args)
        self.now = horizon
        return self

    # --------------------------------------------------------------- transport
    def _send(self, a, b, delay, kind, ident, fn, args):
        if self.down[a][b]:
            self.c["lost"] += 1
            return
        if self.blackhole[a][b]:
            if self.cfg.transport == "tcp":
                self.buffer.setdefault((a, b), []).append((fn, args))
                self.c["buffered"] += 1
            else:
                self.c["lost"] += 1
            return
        p = self.loss[a][b]
        if p > 0.0:
            u = u01((self.seed, kind, ident, a, b, int(self.now * 1000.0)))
            if self.cfg.transport == "tcp":
                k = int(math.log(u) / math.log(p))
                if k > 0:
                    k = min(k, self.cfg.rto_max_k)
                    rto = max(self.cfg.rto_min, 3.0 * self.lat[a][b] * self.mult[a][b])
                    delay += rto * ((1 << k) - 1)
            elif u < p:
                self.c["lost"] += 1
                return
        heapq.heappush(self._heap, (self.now + delay, next(self._seq), self._deliver,
                                    (a, b, self.epoch[a][b], fn, args)))

    def _deliver(self, a, b, ep, fn, args):
        if self.down[a][b] or self.epoch[a][b] != ep:
            self.c["lost"] += 1
            return
        fn(*args)

    # ------------------------------------------------------------ transactions
    def _tx_arrival(self, k):
        x = self._arrival_order[k]
        self._accept_tx(self.origin[x], x, -1)
        k += 1
        if k < len(self._arrival_order):
            self.at(self.created[self._arrival_order[k]], self._tx_arrival, k)

    def _accept_tx(self, i, x, frm):
        s = self.seen[i]
        if x in s:
            self.c["dup_tx_msgs"] += 1
            return False
        if self.cap is not None and not self._admit(i, x):
            return False
        s[x] = self.now
        self.mempool[i][x] = self.now
        self._relay_tx(i, x, frm)
        return True

    # ------------------------------------------- Extension C: bounded mempools
    def _admit(self, i, x):
        """Admission of a transaction new to node i when the mempool is capped (rule in EXTENSIONS.md):
        reject below the rolling minimum fee; if full, accept only by evicting a lower fee rate."""
        f = self.fee[x]
        if f < self.min_fee[i]:
            self._drop(i, x, "rejected")
            return False
        if len(self.mempool[i]) >= self.cap:
            y = self._lowest(i)
            if y is None or f <= self.fee[y]:
                self._drop(i, x, "rejected")          # the newcomer is the lowest: Core trims it straight out
                return False
            del self.mempool[i][y]
            self._drop(i, y, "evicted")
        heapq.heappush(self._fee_heap[i], (f, x))
        return True

    def _drop(self, i, x, why):
        """Node i evicts or rejects x: remember it (recently-rejected memory) and raise its minimum fee."""
        f = self.fee[x]
        if f > self.min_fee[i]:
            self.min_fee[i] = f
        self.dropped[i][x] = (self.now, why)
        self.seen[i].setdefault(x, self.now)
        self.c[why] += 1

    def _lowest(self, i):
        h = self._fee_heap[i]
        mp = self.mempool[i]
        while h:
            y = h[0][1]
            if y in mp:
                return y
            heapq.heappop(h)
        return None

    def _trim(self, i):
        mp = self.mempool[i]
        while len(mp) > self.cap:
            y = self._lowest(i)
            del mp[y]
            self._drop(i, y, "evicted")

    def _refused(self, i, x):
        """A delivered transaction (resync or pull) was refused by node i's mempool policy."""
        self.c["refused_deliveries"] += 1
        self.policy.on_refused(i, x)

    def _relay_tx(self, i, x, frm):
        cfg = self.cfg
        f = cfg.tx_hop_factor
        tm = cfg.trickle_mean
        lat_i = self.lat[i]
        mult_i = self.mult[i]
        seed = self.seed
        send = self._send
        recv = self._accept_tx
        for j in self.peers[i]:
            if j == frm:
                continue
            tr = -tm * math.log(u01((seed, 11, x, i, j)))
            self.c["tx_msgs"] += 1
            send(i, j, f * lat_i[j] * mult_i[j] + tr, 1, x, recv, (j, x, i))

    # ------------------------------------------------------------------ blocks
    def _block_delay(self, a, b, bid, hops=None):
        cfg = self.cfg
        h = cfg.block_hop_factor if hops is None else hops
        return (h * self.lat[a][b] * self.mult[a][b]
                + len(self.blocks[bid].txs) * cfg.tx_bytes / cfg.bandwidth + cfg.block_validation)

    def _mine(self, k):
        cfg = self.cfg
        m = int(self.scn.block_miners[k])
        mp = self.mempool[m]
        cap = cfg.block_capacity
        if len(mp) <= cap:
            txs = tuple(mp)
        else:
            txs = tuple(heapq.nlargest(cap, mp, key=self.fee.__getitem__))
        parent = self.tip[m]
        bid = len(self.blocks)
        self.blocks.append(Block(bid, parent, self.blocks[parent].height + 1, m, txs, self.now))
        self.c["mined"] += 1
        self._recv_block(m, bid, -1)
        k += 1
        if k < len(self.scn.block_times):
            self.at(float(self.scn.block_times[k]), self._mine, k)

    def _recv_block(self, i, bid, frm):
        kn = self.known[i]
        if bid in kn:
            self.c["dup_block_msgs"] += 1
            return
        b = self.blocks[bid]
        if b.parent not in kn:
            lst = self.orphans[i].setdefault(b.parent, [])
            if bid not in lst:
                lst.append(bid)
            if frm >= 0:
                self._send(i, frm, self.lat[i][frm] * self.mult[i][frm], 3, b.parent,
                           self._serve_block, (frm, i, b.parent))
            return
        kn.add(bid)
        if b.height > self.blocks[self.tip[i]].height:
            self._set_tip(i, bid)
            self._relay_block(i, bid, frm)
        kids = self.orphans[i].pop(bid, None)
        if kids:
            for c_ in kids:
                self._recv_block(i, c_, frm)

    def _serve_block(self, src, dst, bid):
        if bid in self.known[src]:
            self.c["block_msgs"] += 1
            self._send(src, dst, self._block_delay(src, dst, bid, hops=1.0), 4, bid,
                       self._recv_block, (dst, bid, src))

    def _relay_block(self, i, bid, frm):
        for j in self.peers[i]:
            if j == frm:
                continue
            self.c["block_msgs"] += 1
            self._send(i, j, self._block_delay(i, j, bid), 2, bid, self._recv_block, (j, bid, i))

    def _set_tip(self, i, new):
        blocks = self.blocks
        chain = self.chain[i]
        branch = []
        cur = blocks[new]
        while not (cur.height < len(chain) and chain[cur.height] == cur.id):
            branch.append(cur.id)
            cur = blocks[cur.parent]
        fork_h = cur.height
        conf = self.conf[i]
        mp = self.mempool[i]
        seen = self.seen[i]
        returned = []
        for h in range(len(chain) - 1, fork_h, -1):
            for x in blocks[chain[h]].txs:
                conf.discard(x)
                returned.append(x)
        del chain[fork_h + 1:]
        now = self.now
        for bid in reversed(branch):
            chain.append(bid)
            for x in blocks[bid].txs:
                conf.add(x)
                mp.pop(x, None)
                if x not in seen:
                    seen[x] = now
        self.tip[i] = new
        if returned:
            self.c["reorgs"] += 1
            for x in returned:
                if x not in conf and x not in mp:
                    mp[x] = now
                    self.c["reorg_returned"] += 1
                    if self.cap is not None:
                        heapq.heappush(self._fee_heap[i], (self.fee[x], x))
                    if self.cfg.relay_reorged:
                        self._relay_tx(i, x, -1)
            if self.cap is not None:
                self._trim(i)                  # Core: re-add after a reorg, then limit the mempool size

    def chain_sync(self, a, b):
        """Headers-first sync on (re)connection: a sends b the active-chain blocks b lacks."""
        chain = self.chain[a]
        kn = self.known[b]
        missing = []
        for h in range(len(chain) - 1, 0, -1):
            bid = chain[h]
            if bid in kn:
                break
            missing.append(bid)
        missing.reverse()
        base = 3.0 * self.lat[a][b] * self.mult[a][b]
        for idx, bid in enumerate(missing):
            self.c["block_msgs"] += 1
            self._send(a, b, base + idx * 1e-6 + self._block_delay(a, b, bid, hops=0.0), 5, bid,
                       self._recv_block, (b, bid, a))

    # ------------------------------------------------------ recovery actions
    def mempool_sync(self, a, b, ctr, done=None):
        """Full pending-transaction exchange a -> b (announce all hashes, b pulls what it lacks)."""
        hashes = list(self.mempool[a])
        ctr["announced"] += len(hashes)
        ctr["messages"] += 1
        self._send(a, b, self.lat[a][b] * self.mult[a][b], 6, len(hashes), self._sync_inv,
                   (a, b, hashes, ctr, done))

    def _sync_inv(self, a, b, hashes, ctr, done):
        s = self.seen[b]
        req = [x for x in hashes if x not in s]
        if not req:
            if done:
                done()
            return
        ctr["requested"] += len(req)
        ctr["messages"] += 1
        self._send(b, a, self.lat[b][a] * self.mult[b][a], 7, len(req), self._serve_txs,
                   (a, b, req, ctr, done))

    def pull(self, i, j, txs, ctr):
        """Audit-directed pull: node i requests specific transactions from neighbour j."""
        ctr["requested"] += len(txs)
        ctr["messages"] += 1
        self._send(i, j, self.lat[i][j] * self.mult[i][j], 9, len(txs), self._serve_txs,
                   (j, i, txs, ctr, None))

    def _serve_txs(self, src, dst, req, ctr, done):
        s = self.seen[src]
        if self.cap is None:
            have = [x for x in req if x in s]
        else:       # Extension C: an evicted or rejected transaction can no longer be served
            mp, cf = self.mempool[src], self.conf[src]
            have = [x for x in req if x in mp or x in cf]
        ctr["messages"] += 1
        cfg = self.cfg
        d = self.lat[src][dst] * self.mult[src][dst] + len(have) * cfg.tx_bytes / cfg.bandwidth
        self._send(src, dst, d, 10, len(have), self._recv_txs, (src, dst, have, ctr, done))

    def _recv_txs(self, src, dst, txs, ctr, done):
        s = self.seen[dst]
        for x in txs:
            ctr["transfers"] += 1
            if x in s:
                ctr["unnecessary"] += 1
                if self.cap is not None and x in self.dropped[dst] and x not in self.mempool[dst] \
                        and x not in self.conf[dst]:
                    self._refused(dst, x)        # in the node's recently-rejected memory
            else:
                ok = self._accept_tx(dst, x, src)
                if not ok and self.cap is not None:
                    self._refused(dst, x)        # rejected by admission (minimum fee or full mempool)
        if done:
            done()

    # ------------------------------------------------------------ disturbances
    def _outage(self, a, b):
        if self.cfg.outage_mode == "reset":
            for x, y in ((a, b), (b, a)):
                self.down[x][y] = True
                self.epoch[x][y] += 1
        else:
            for x, y in ((a, b), (b, a)):
                self.blackhole[x][y] = True
                self.bh_since[(x, y)] = self.now
        self.outage_edges.append((a, b))

    def _dist_start(self):
        d = self.scn.disturbance
        cfg = self.cfg
        if d.kind == "partition":
            A = set(d.group_a)
            for a, b in self.edges:
                if (a in A) != (b in A):
                    self._outage(a, b)
        elif d.kind == "isolation":
            for v in d.nodes:
                for p in self.peers[v]:
                    self._outage(min(v, p), max(v, p))
        elif d.kind == "loss":
            for v in d.nodes:
                for p in self.peers[v]:
                    self.loss[v][p] = self.loss[p][v] = cfg.loss_p
        elif d.kind == "latency":
            for v in d.nodes:
                for p in self.peers[v]:
                    self.mult[v][p] = self.mult[p][v] = cfg.latency_mult
        elif d.kind == "asymmetric":
            for v in d.nodes:
                for p in self.peers[v]:
                    self.blackhole[v][p] = True
                    self.bh_since[(v, p)] = self.now
        # burst: the extra transactions are already in the workload

    def _dist_end(self):
        cfg = self.cfg
        n = self.n
        for a in range(n):
            for b in range(n):
                self.loss[a][b] = 0.0
                self.mult[a][b] = 1.0
        # heal blackholes: flush TCP buffers after a residual backoff
        for (a, b), since in list(self.bh_since.items()):
            self.blackhole[a][b] = False
            buf = self.buffer.pop((a, b), [])
            if buf:
                elapsed = self.now - since
                delta = u01((self.seed, 30, a, b, 0)) * min(elapsed, cfg.buffer_flush_cap)
                base = delta + self.lat[a][b]
                for idx, (fn, args) in enumerate(buf):
                    heapq.heappush(self._heap, (self.now + base + idx * 1e-6, next(self._seq),
                                                self._deliver, (a, b, self.epoch[a][b], fn, args)))
        self.bh_since.clear()
        # reset outages: peers reconnect after a short random delay
        if cfg.outage_mode == "reset":
            for a, b in self.outage_edges:
                delay = u01((self.seed, 31, a, b, 0)) * cfg.reconnect_max
                self.at(self.now + delay, self._reconnect, a, b)
        self.outage_edges = []

    def _reconnect(self, a, b):
        for x, y in ((a, b), (b, a)):
            self.down[x][y] = False
            self.epoch[x][y] += 1
        self.chain_sync(a, b)
        self.chain_sync(b, a)
        self.policy.on_reconnect(a, b)

    # -------------------------------------------------- connectivity monitor
    def _ping(self, a, b, k):
        if self.down[a][b] or self.down[b][a] or self.blackhole[a][b] or self.blackhole[b][a]:
            return FAIL
        p1, p2 = self.loss[a][b], self.loss[b][a]
        if p1 > 0.0 and u01((self.seed, 20, k, a, b)) < p1:
            return FAIL
        if p2 > 0.0 and u01((self.seed, 21, k, a, b)) < p2:
            return FAIL
        rtt = self.lat[a][b] * self.mult[a][b] + self.lat[b][a] * self.mult[b][a]
        if rtt > self.cfg.ping_timeout:
            return FAIL
        if rtt > self.cfg.rtt_slow_factor * 2.0 * self.lat[a][b]:
            return SLOW
        return OK

    def _ping_round(self):
        cfg = self.cfg
        k = self.m_round
        self.m_round += 1
        for e, (a, b) in enumerate(self.edges):
            res = self._ping(a, b, k)
            self.m_last[e] = res
            w = self.m_window[e]
            w.append(res)
            if self.m_healthy[e]:
                if res == SLOW or sum(1 for r in w if r == FAIL) >= cfg.ping_fail_threshold:
                    self.m_healthy[e] = False
                    self.m_okstreak[e] = 0
                    self.m_unhealthy += 1
                    self.monitor_log.append((self.now, "edge_down", a, b))
                    if self.m_unhealthy == 1:
                        self.monitor_log.append((self.now, "alarm", -1, -1))
                        self.policy.on_alarm(self.now)
            else:
                self.m_okstreak[e] = self.m_okstreak[e] + 1 if res == OK else 0
                if self.m_okstreak[e] >= cfg.healthy_streak:
                    self.m_healthy[e] = True
                    w.clear()
                    self.m_unhealthy -= 1
                    self.monitor_log.append((self.now, "edge_up", a, b))
                    self.policy.on_edge_recovered(a, b, self.now)
                    if self.m_unhealthy == 0:
                        self.monitor_log.append((self.now, "recovered", -1, -1))
                        self.policy.on_network_recovered(self.now)
        self.at(self.now + cfg.ping_interval, self._ping_round)

    def link_usable(self, i, j):
        """Monitor's view of a link: usable unless its most recent ping failed."""
        return self.m_last[self.edge_index[(min(i, j), max(i, j))]] != FAIL

    @property
    def connectivity_healthy(self):
        return self.m_unhealthy == 0

    # ------------------------------------------------------------ chain views
    def best_tip(self):
        """Highest tip; ties broken by number of nodes on it, then lowest id. Returns (bid, node)."""
        counts = {}
        for i, t in enumerate(self.tip):
            counts.setdefault(t, []).append(i)
        best = max(counts, key=lambda b: (self.blocks[b].height, len(counts[b]), -b))
        return best, counts[best][0]

    def ancestor_at(self, bid, h):
        b = self.blocks[bid]
        while b.height > h:
            b = self.blocks[b.parent]
        return b.id

    def chain_consistent(self, best=None):
        tips = set(self.tip)
        if len(tips) == 1:
            return True
        if best is None:
            best, _ = self.best_tip()
        for t in tips:
            if t == best:
                continue
            if self.ancestor_at(best, self.blocks[t].height) != t:
                return False
        return True

    # ----------------------------------------------------------- evaluator
    def _evaluate(self):
        cfg = self.cfg
        t = self.now
        mps = self.mempool
        confs = self.conf
        created = self.created
        union = set()
        for mp in mps:
            union.update(mp.keys())
        best, bnode = self.best_tip()
        best_conf = confs[bnode]
        cut = t - cfg.tau_m
        R = {x for x in union if created[x] <= cut}
        R -= best_conf
        nR = len(R)
        unknown = [R.difference(mps[i].keys()).difference(confs[i]) for i in range(self.n)]
        U = len(set().union(*unknown)) if nR else 0
        D = pairwise_jaccard(unknown, nR) if U else 0.0
        sizes = sorted(len(mp) for mp in mps)
        B = float(np.median(sizes)) / cfg.block_capacity
        ok = self.chain_consistent(best)
        s = self.series
        s["t"].append(t)
        s["U"].append(U)
        s["D"].append(D)
        s["B"].append(B)
        s["chain_ok"].append(ok)
        s["n_tips"].append(len(set(self.tip)))
        s["pend"].append(len(union))
        for c_ in self.cutoffs:
            if t + 60.0 < c_:
                s[f"res@{c_:g}"].append(np.nan)
                continue
            # only mature transactions count: created before the disturbance ended AND at
            # least tau_m ago, so ordinary in-flight propagation is never called residue
            s[f"res@{c_:g}"].append(len(residue_set(union, mps, confs, created, min(c_, cut))))
        if self.cap is not None:
            self._evaluate_capacity(t, union, best_conf, cut)
        if t + cfg.eval_interval <= cfg.horizon + 1e-9:
            self.at(t + cfg.eval_interval, self._evaluate)

    def _evaluate_capacity(self, t, union, best_conf, cut):
        """Extension C ground truth (the residue definition is unchanged): split the residue candidates some
        node lacks into evicted-divergence (that node evicted or rejected them) and gossip residue (it never
        dropped them); count lost transactions (dropped somewhere, now pending nowhere and unconfirmed)."""
        s = self.series
        mps, confs, created, dropped = self.mempool, self.conf, self.created, self.dropped
        sizes = [len(mp) for mp in mps]
        s["max_mp"].append(max(sizes))
        s["n_full"].append(sum(1 for z in sizes if z >= self.cap))
        gone = set()
        for d in dropped:
            gone.update(d.keys())
        s["lost"].append(sum(1 for x in gone if created[x] <= cut and x not in union and x not in best_conf))
        for c_ in self.cutoffs:
            if t + 60.0 < c_:
                s[f"evdiv@{c_:g}"].append(np.nan)
                s[f"gres@{c_:g}"].append(np.nan)
                continue
            lim = min(c_, cut)
            cand = {x for x in union if created[x] < lim}
            ev, gr = set(), set()
            for mp, cf, dr in zip(mps, confs, dropped):
                lack = cand.difference(mp.keys()).difference(cf)
                if lack:
                    d = lack.intersection(dr.keys())
                    ev |= d
                    gr |= lack.difference(d)
            s[f"evdiv@{c_:g}"].append(len(ev))
            s[f"gres@{c_:g}"].append(len(gr))


def residue_set(pending_union, mempools, confirmed, created, cutoff):
    """Res(t): transactions created before `cutoff` that some node has pending while another
    node has neither pending nor confirmed on its active chain (threshold-free)."""
    cand = {x for x in pending_union if created[x] < cutoff}
    res = set()
    for mp, cf in zip(mempools, confirmed):
        res |= cand.difference(mp.keys()).difference(cf)
    return res


def pairwise_jaccard(unknown, nR):
    """Mean pairwise Jaccard distance between knowledge sets V_i = R minus unknown_i.

    |V_i & V_j| = nR - |u_i | u_j| and |V_i | V_j| = nR - |u_i & u_j|.
    """
    n = len(unknown)
    if nR == 0:
        return 0.0
    tot = 0.0
    pairs = 0
    for i in range(n):
        ui = unknown[i]
        for j in range(i + 1, n):
            uj = unknown[j]
            pairs += 1
            if not ui and not uj:
                continue
            inter = nR - len(ui | uj)
            union = nR - len(ui & uj)
            tot += (1.0 - inter / union) if union > 0 else 0.0
    return tot / pairs if pairs else 0.0
