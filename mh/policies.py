"""Recovery policies: Baseline 1, Baseline 2 and the SARA framework.

All policies see the same shared connectivity monitor. Only SARA reads node
state. Every policy keeps a status timeline ("incident" / "recovered") from
which the evaluation derives detection time, declared recovery time and
false-recovery exposure.

SARA is one class with three toggles (the ablation never forks the code):
  use_divergence  : set-level divergence detection; off -> mempool-size proxy
  use_risk        : tiered risk assessment; off -> act on any divergence, no backlog
  use_verification: closed-loop recovery verification; off -> one round, then declare
"""
from __future__ import annotations

import statistics
from collections import defaultdict

from .sim import pairwise_jaccard

LOW, MODERATE, HIGH, CRITICAL = 0, 1, 2, 3
TIER_NAMES = ("LOW", "MODERATE", "HIGH", "CRITICAL")


def risk_tier(r, exceed, n_gap, n, cfg):
    """Map the risk ratio to (raw tier, effective tier).

    raw: LOW r<1, MODERATE 1<=r<2, HIGH 2<=r<4, CRITICAL r>=4.
    effective: raw after debounce (needs `open_debounce` consecutive exceedances),
    +1 tier after `persist_escalation` consecutive exceedances, and at least HIGH
    when half or more of the nodes have a knowledge gap.
    """
    raw = LOW if r < 1 else MODERATE if r < 2 else HIGH if r < 4 else CRITICAL
    tier = raw if exceed >= cfg.open_debounce else LOW
    if tier >= MODERATE and exceed >= cfg.persist_escalation:
        tier = min(CRITICAL, tier + 1)
    if tier >= MODERATE and n_gap >= n / 2:
        tier = max(tier, HIGH)
    return raw, tier


def new_counter():
    return dict(announced=0, requested=0, transfers=0, unnecessary=0, messages=0,
                rounds=0, snapshot_ids=0, snapshot_delta_ids=0, audits=0, resyncs=0)


class Policy:
    name = "base"

    def __init__(self, sim):
        self.sim = sim
        self.cfg = sim.cfg
        self.is_open = False
        self.incidents = []          # [open_time, close_time or None, source]
        self.timeline = [(0.0, "recovered")]
        self.ctr = new_counter()
        self.reopened = 0
        self.closed_once = False
        self.alarms = []             # (time, source) every time an alarm is raised
        self.log = []                # human-readable audit trail

    # ---------------- incident bookkeeping ----------------
    def open(self, t, source):
        if self.is_open:
            return
        self.is_open = True
        if self.closed_once:
            self.reopened += 1
        self.incidents.append([t, None, source])
        self.timeline.append((t, "incident"))
        self.log.append((t, f"INCIDENT OPENED ({source})"))

    def close(self, t, note=""):
        if not self.is_open:
            return
        self.is_open = False
        self.closed_once = True
        self.incidents[-1][1] = t
        self.timeline.append((t, "recovered"))
        self.log.append((t, f"RECOVERY DECLARED{(' — ' + note) if note else ''}"))

    # ---------------- hooks (overridden as needed) ----------------
    def on_start(self):
        pass

    def on_alarm(self, t):
        self.alarms.append((t, "connectivity"))
        self.open(t, "connectivity")

    def on_edge_recovered(self, a, b, t):
        pass

    def on_network_recovered(self, t):
        pass

    def on_reconnect(self, a, b):
        pass

    def on_refused(self, i, x):
        """Extension C only: node i's mempool policy refused a delivered transaction x."""
        pass

    def summary(self):
        return dict(policy=self.name, incidents=[tuple(i) for i in self.incidents],
                    timeline=list(self.timeline), counters=dict(self.ctr), reopened=self.reopened,
                    alarms=list(self.alarms))


class B1(Policy):
    """Connectivity-only: recovery is declared the moment every link is healthy again."""
    name = "B1"

    def on_network_recovered(self, t):
        self.close(t, "connectivity restored")


class B2(Policy):
    """Protocol resync: on reconnection (or monitor-reported link recovery) both ends exchange
    every pending transaction hash and pull what they lack, plus chain sync. Recovery is declared
    when connectivity is restored and every resync exchange has been delivered."""
    name = "B2"
    RESYNC_TIMEOUT = 30.0

    def __init__(self, sim):
        super().__init__(sim)
        self.synced = set()
        self.pending = 0
        self.net_ok_at = None

    def on_alarm(self, t):
        self.alarms.append((t, "connectivity"))
        self.open(t, "connectivity")
        self.synced = set()
        self.net_ok_at = None

    def _resync(self, a, b, chain=True):
        e = (min(a, b), max(a, b))
        self.synced.add(e)
        self.ctr["resyncs"] += 1
        self.log.append((self.sim.now, f"RESYNC link {a}-{b}: full pending-hash exchange"
                                       f"{' + chain sync' if chain else ''}"))
        if chain:
            self.sim.chain_sync(a, b)
            self.sim.chain_sync(b, a)
        self.pending += 2
        self.sim.mempool_sync(a, b, self.ctr, self._done)
        self.sim.mempool_sync(b, a, self.ctr, self._done)

    def _done(self):
        self.pending -= 1
        self._try_close()

    def on_reconnect(self, a, b):
        # protocol behaviour (geth syncTransactions): a fresh connection gets the peer's pending set
        self._resync(a, b, chain=False)  # chain sync already done by the reconnection handshake

    def on_edge_recovered(self, a, b, t):
        e = (min(a, b), max(a, b))
        if self.is_open and e not in self.synced:
            self._resync(a, b, chain=True)   # forced re-handshake after a degradation

    def on_network_recovered(self, t):
        self.net_ok_at = t
        self._try_close()
        self.sim.at(t + self.RESYNC_TIMEOUT, self._timeout)

    def _timeout(self):
        if self.is_open and self.net_ok_at is not None and self.sim.connectivity_healthy:
            self.close(self.sim.now, "resync timeout")

    def _try_close(self):
        if self.is_open and self.net_ok_at is not None and self.pending <= 0 and self.sim.connectivity_healthy:
            self.close(self.sim.now, "connectivity restored and resync delivered")


class SARA(Policy):
    """State-Aware Recovery Audit: monitoring -> divergence detection -> risk assessment ->
    recovery verification, with audit-directed pull reconciliation as the control action."""

    def __init__(self, sim, use_divergence=True, use_risk=True, use_verification=True):
        super().__init__(sim)
        self.use_div = use_divergence
        self.use_risk = use_risk
        self.use_ver = use_verification
        self.name = "SARA" + ("" if use_divergence else "-D") + ("" if use_risk else "-R") + \
            ("" if use_verification else "-V")
        self.first_obs = {}
        self.exceed = 0
        self.low_streak = 0
        self.conn_alarm = False
        self.incident_conn = False
        self.stopped = False
        self.prev_state_alarm = False
        self.outstanding = {}        # (node, tx) -> time of the last pull request
        self.prev_tier = LOW
        self.prev_snap = None
        self.audit_log = []
        # Extension C: a (node, tx) gap the node refused (evicted it, or the tx is below its minimum fee) would be
        # refused again, so it is never pulled again; it stays in the divergence measure (the incident stays open)
        self.unrepairable = set()
        self._refused_new = 0
        if self.cfg.mempool_cap is not None:
            self.ctr["unrepairable"] = 0

    def on_start(self):
        self.sim.at(self.cfg.audit_interval, self.audit)

    def on_refused(self, i, x):
        if (i, x) not in self.unrepairable:
            self.unrepairable.add((i, x))
            self.ctr["unrepairable"] += 1
            self._refused_new += 1

    def on_alarm(self, t):
        self.conn_alarm = True
        self.alarms.append((t, "connectivity"))
        if not self.stopped:
            self.incident_conn = True
            self.open(t, "connectivity")

    def on_network_recovered(self, t):
        self.conn_alarm = False

    # ---------------- the audit cycle ----------------
    def audit(self):
        sim = self.sim
        cfg = self.cfg
        t = sim.now
        n = sim.n
        mps = sim.mempool
        confs = sim.conf
        self.ctr["audits"] += 1

        # 1. state monitoring: snapshot every node's mempool (IDs + entry times) and tip
        sizes = [len(mp) for mp in mps]
        self.ctr["snapshot_ids"] += sum(sizes)
        snap = [set(mp.keys()) for mp in mps]
        if self.prev_snap is None:
            self.ctr["snapshot_delta_ids"] += sum(sizes)
        else:
            self.ctr["snapshot_delta_ids"] += sum(len(a ^ b) for a, b in zip(snap, self.prev_snap))
        self.prev_snap = snap
        union = set()
        for mp in mps:
            union.update(mp.keys())
        fo = self.first_obs
        for x in union.difference(fo.keys()):
            fo[x] = min(mp[x] for mp in mps if x in mp)
        best, bnode = sim.best_tip()
        chain_ok = sim.chain_consistent(best)

        # 2. divergence detection (or the -D size proxy)
        unknown = None
        if self.use_div:
            cut = t - cfg.tau_m
            R = {x for x in union if fo[x] <= cut}
            R -= confs[bnode]
            nR = len(R)
            unknown = [R.difference(mps[i].keys()).difference(confs[i]) for i in range(n)]
            n_gap = sum(1 for u in unknown if u)
            D = pairwise_jaccard(unknown, nR) if n_gap else 0.0
            self.last_nR = nR
            # control limit: the clean-run percentile, floored at the measurement resolution
            # (one missing transaction at one node at the current reference size)
            eps = max(cfg.eps_D, 2.0 / (n * nR)) if nR else max(cfg.eps_D, 1e-12)
            div_ratio = D / eps
            flagged = [i for i in range(n) if unknown[i]]
        else:
            # count-based monitoring done competently: compare mempool sizes only among
            # nodes on the best tip (others are mid-block-propagation and differ for
            # benign reasons), normalised by at least half a block
            sync = [i for i in range(n) if sim.tip[i] == best]
            med = statistics.median([sizes[i] for i in sync])
            norm = max(med, cfg.block_capacity / 2.0)
            dev = [abs(sizes[i] - med) / norm if sim.tip[i] == best else 0.0 for i in range(n)]
            D = max(dev)
            div_ratio = D / cfg.eps_size
            flagged = [i for i in range(n) if dev[i] > cfg.eps_size]
            n_gap = len(flagged)
            self.last_nR = len(union)
        B = statistics.median(sizes) / cfg.block_capacity

        # 3. risk assessment
        if self.use_risk:
            r = max(div_ratio, B / cfg.beta)
            self.exceed = self.exceed + 1 if r >= 1 else 0
            raw, tier = risk_tier(r, self.exceed, n_gap, n, cfg)
            state_alarm = tier >= MODERATE
            consistent = raw == LOW
        else:
            r = float("inf") if D > 0 else 0.0
            raw = tier = MODERATE if D > 0 else LOW
            state_alarm = D > 0
            consistent = D == 0

        self.audit_log.append((t, D, B, r, tier, n_gap, chain_ok, len(union), self.last_nR))
        if state_alarm and not self.prev_state_alarm:
            self.alarms.append((t, f"state {TIER_NAMES[tier]}"))
        self.prev_state_alarm = state_alarm
        if tier != self.prev_tier and not self.stopped:
            what = "D" if self.use_div else "size dev"
            self.log.append((t, f"RISK {TIER_NAMES[tier]}: {what}={D:.4f}, {n_gap}/{n} nodes flagged, "
                                f"backlog {B:.2f} blocks"))
            self.prev_tier = tier
        if self._refused_new:
            if not self.stopped:
                self.log.append((t, f"ESCALATE: {self._refused_new} pulled tx refused by node policy (evicted or "
                                    f"below its minimum fee); gap left open, operator action required"))
            self._refused_new = 0

        # 4. incident handling, control action and recovery verification
        conn_ok = sim.connectivity_healthy
        if not self.stopped and not self.is_open and state_alarm:
            self.incident_conn = self.conn_alarm
            self.open(t, f"state {TIER_NAMES[tier]}")

        if self.is_open and not self.stopped:
            if self.use_ver:
                if state_alarm:
                    self._act(tier, unknown, flagged)
                if conn_ok and consistent and chain_ok:
                    self.low_streak += 1
                else:
                    self.low_streak = 0
                if self.low_streak >= cfg.verify_window:
                    self.close(t, f"state verified LOW for {cfg.verify_window} audits")
                    self.low_streak = 0
            else:
                # open loop: behave as SARA until connectivity is back (or, for a state-only
                # incident, act once at detection), then run one round and declare recovery
                if self.incident_conn and not conn_ok:
                    if state_alarm:
                        self._act(tier, unknown, flagged)
                else:
                    self._act(max(tier, MODERATE), unknown, flagged)
                    self.close(t, "one reconciliation round executed (not verified)")
                    self.stopped = True

        # schedule the next audit (halved interval at HIGH and above)
        dt = cfg.audit_interval
        if self.use_risk and self.is_open and tier >= HIGH:
            dt /= 2.0
        sim.at(t + dt, self.audit)

    def _act(self, tier, unknown, flagged):
        sim = self.sim
        if not flagged:
            return
        self.ctr["rounds"] += 1
        t = sim.now
        retry = self.cfg.pull_retry
        self._round_ids = 0
        self._round_nodes = set()
        if self.use_div:
            sources = 1 if (tier <= MODERATE or not self.use_risk) else 2
            mps, confs = sim.mempool, sim.conf
            out = self.outstanding
            skip = self.unrepairable
            for i in flagged:
                # pull only through links the monitor currently sees as up
                nbrs = sorted((j for j in sim.peers[i] if sim.link_usable(i, j)), key=lambda j: sim.lat[i][j])
                if not nbrs:
                    continue
                plan = defaultdict(list)
                for x in unknown[i]:
                    if skip and (i, x) in skip:
                        continue            # Extension C: refused by node policy, never pulled again
                    last = out.get((i, x))
                    if last is not None and t - last < retry:
                        continue            # a request for this tx is still in flight
                    got = 0
                    for j in nbrs:
                        if x in mps[j] or x in confs[j]:
                            plan[j].append(x)
                            got += 1
                            if got >= sources:
                                break
                    if got:
                        out[(i, x)] = t
                for j, txs in plan.items():
                    sim.pull(i, j, txs, self.ctr)
                    self._round_ids += len(txs)
                    self._round_nodes.add(i)
        else:
            # without set-level knowledge the only repair is a full exchange with a neighbour
            out = self.outstanding
            for i in flagged:
                nbrs = [j for j in sim.peers[i] if sim.link_usable(i, j)]
                if not nbrs:
                    continue
                last = out.get((i, -1))
                if last is not None and t - last < retry:
                    continue
                out[(i, -1)] = t
                j = max(nbrs, key=lambda p: (len(sim.mempool[p]), -p))
                self.ctr["resyncs"] += 1
                sim.mempool_sync(i, j, self.ctr)
                sim.mempool_sync(j, i, self.ctr)
                self._round_nodes.add(i)
        if self._round_nodes:
            if self.use_div:
                self.log.append((t, f"RECONCILE: {len(self._round_nodes)} node(s) pull {self._round_ids} missing tx IDs"))
            else:
                self.log.append((t, f"RECONCILE: full mempool exchange for {len(self._round_nodes)} node(s)"))


def make_policy(name: str):
    """Factory: returns a callable sim -> Policy."""
    if name == "B1":
        return lambda sim: B1(sim)
    if name == "B2":
        return lambda sim: B2(sim)
    if name == "SARA":
        return lambda sim: SARA(sim)
    if name == "SARA-D":
        return lambda sim: SARA(sim, use_divergence=False)
    if name == "SARA-R":
        return lambda sim: SARA(sim, use_risk=False)
    if name == "SARA-V":
        return lambda sim: SARA(sim, use_verification=False)
    raise ValueError(name)
