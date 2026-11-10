"""Member 4 - Proof-of-Stake ledger for every agreed trade.

Design (simulated, single process - no networking, as allowed by the course):

* Each time step produces ONE block that contains every P2P and LOCAL
  transaction agreed in that step (an empty block is still produced when no
  trade happens, so the chain always has one block per step).
* Transactions are hashed with SHA-256 over a canonical JSON encoding; the
  block stores the Merkle root of those hashes.
* At least 10 validators, each with a stake and a secret signing key
  generated with the operating system's secure random generator (so nobody
  can re-sign a modified block without the keys).
  The block proposer is chosen with stake-weighted pseudo-random selection,
  seeded by the previous block hash (deterministic and reproducible); faulty
  validators are never chosen as proposer.
* Every validator independently re-checks the proposed block (transaction
  rules, Merkle root, link to previous block, block hash) and signs it with
  HMAC-SHA256 if it is valid. The block is final when validators holding
  MORE than 2/3 of the total stake have signed (BFT-style quorum).
* The proposer receives a small stake reward, so stake evolves over time.
* verify_chain() recomputes everything from scratch: hashes, Merkle roots,
  links, signatures, quorum, proposer choice and stake evolution, and the
  chain length / tip against what the simulation recorded. Any change made
  without the validators' secret keys is detected (tamper check).
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import random
import secrets
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from .contract import BlockResult, Transaction, validate_transaction

GENESIS_PREV_HASH = "0" * 64
QUORUM_FRACTION = 2.0 / 3.0
MIN_VALIDATORS = 10


def sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def tx_hash(tx: Dict) -> str:
    return sha256(canonical(tx))


def merkle_root(hashes: List[str]) -> str:
    if not hashes:
        return sha256("")
    level = list(hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [sha256(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


@dataclass
class Validator:
    validator_id: str
    stake: float
    secret: str = field(repr=False)
    faulty: bool = False          # a faulty validator never signs

    def sign(self, block_hash: str) -> str:
        return hmac.new(self.secret.encode(), block_hash.encode(), hashlib.sha256).hexdigest()

    def check_signature(self, block_hash: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(block_hash), signature)


@dataclass
class Block:
    index: int
    step: int
    prev_hash: str
    transactions: List[Dict]
    merkle_root: str
    proposer_id: str
    stake_snapshot: Dict[str, float]          # stake of every validator when the block was made
    signatures: Dict[str, str] = field(default_factory=dict)
    block_hash: str = ""

    def header(self) -> Dict:
        return {
            "index": self.index,
            "step": self.step,
            "prev_hash": self.prev_hash,
            "merkle_root": self.merkle_root,
            "proposer_id": self.proposer_id,
            "n_transactions": len(self.transactions),
            "stake_snapshot": self.stake_snapshot,
        }

    def compute_hash(self) -> str:
        return sha256(canonical(self.header()))

    def to_dict(self) -> Dict:
        return asdict(self)


class Blockchain:
    def __init__(self, n_validators: int = 10, seed: int = 42, faulty_validators: int = 0,
                 block_reward: float = 1.0):
        if n_validators < MIN_VALIDATORS:
            raise ValueError(f"the course requires at least {MIN_VALIDATORS} validators")
        if faulty_validators < 0 or faulty_validators >= n_validators:
            raise ValueError("faulty_validators must be between 0 and n_validators - 1")
        rng = random.Random(seed)
        self.validators: Dict[str, Validator] = {}
        for i in range(n_validators):
            vid = f"V{i + 1:02d}"
            self.validators[vid] = Validator(
                validator_id=vid,
                stake=float(rng.randint(50, 150)),
                secret=secrets.token_hex(32),
                faulty=i >= n_validators - faulty_validators,
            )
        self.initial_stakes: Dict[str, float] = {vid: v.stake for vid, v in sorted(self.validators.items())}
        self.block_reward = block_reward
        self.chain: List[Block] = []
        self._tx_ids: set = set()

    # ------------------------------------------------------------------ #
    @property
    def last_hash(self) -> str:
        return self.chain[-1].block_hash if self.chain else GENESIS_PREV_HASH

    def total_stake(self, snapshot: Optional[Dict[str, float]] = None) -> float:
        snap = snapshot if snapshot is not None else {v.validator_id: v.stake for v in self.validators.values()}
        return sum(snap.values())

    def select_proposer(self, prev_hash: str, stakes: Optional[Dict[str, float]] = None) -> str:
        """Stake-weighted deterministic choice seeded by the previous block hash.

        Only non-faulty validators can propose."""
        stakes = stakes if stakes is not None else {vid: v.stake for vid, v in self.validators.items()}
        rng = random.Random(int(prev_hash, 16))
        ids = sorted(v for v in stakes if v in self.validators and not self.validators[v].faulty)
        weights = [stakes[v] for v in ids]
        return rng.choices(ids, weights=weights, k=1)[0]

    # ------------------------------------------------------------------ #
    def _validator_checks(self, block: Block) -> List[str]:
        """What every honest validator verifies before signing."""
        errs: List[str] = []
        for d in block.transactions:
            errs += validate_transaction(Transaction(**d))
            if d["step"] != block.step:
                errs.append(f"{d['transaction_id']}: step differs from block step")
        ids = [d["transaction_id"] for d in block.transactions]
        if len(set(ids)) != len(ids):
            errs.append("duplicate transaction id inside block")
        if any(i in self._tx_ids for i in ids):
            errs.append("transaction already recorded in an earlier block (double spend)")
        if block.prev_hash != self.last_hash:
            errs.append("prev_hash does not match chain tip")
        if block.merkle_root != merkle_root([tx_hash(d) for d in block.transactions]):
            errs.append("merkle root mismatch")
        if block.block_hash != block.compute_hash():
            errs.append("block hash mismatch")
        return errs

    def append_transactions(self, step: int, transactions: List[Transaction]) -> BlockResult:
        tx_dicts = [t.to_dict() for t in transactions]
        prev = self.last_hash
        proposer = self.select_proposer(prev)
        block = Block(
            index=len(self.chain),
            step=step,
            prev_hash=prev,
            transactions=tx_dicts,
            merkle_root=merkle_root([tx_hash(d) for d in tx_dicts]),
            proposer_id=proposer,
            stake_snapshot={vid: v.stake for vid, v in sorted(self.validators.items())},
        )
        block.block_hash = block.compute_hash()

        errs = self._validator_checks(block)
        if not errs:
            for vid, v in sorted(self.validators.items()):
                if not v.faulty:
                    block.signatures[vid] = v.sign(block.block_hash)

        signed_stake = sum(block.stake_snapshot[v] for v in block.signatures)
        valid = not errs and signed_stake > QUORUM_FRACTION * self.total_stake(block.stake_snapshot)
        if not valid:
            reason = "; ".join(errs) if errs else "quorum not reached"
            raise ValueError(f"block for step {step} rejected: {reason}")

        self.chain.append(block)
        self._tx_ids.update(d["transaction_id"] for d in tx_dicts)
        self.validators[proposer].stake += self.block_reward
        return BlockResult(step=step, block_index=block.index, block_hash=block.block_hash,
                           proposer_id=proposer, validator_ids=sorted(block.signatures),
                           n_transactions=len(tx_dicts), valid=True)

    # ------------------------------------------------------------------ #
    def verify_chain(self, chain: Optional[List[Block]] = None,
                     expected_blocks: Optional[List[BlockResult]] = None) -> Tuple[bool, List[str]]:
        """Recompute every hash, link, Merkle root, signature, quorum, proposer and stake.

        expected_blocks: the BlockResult list recorded by the simulation, used to
        detect blocks removed from the end or a replaced chain tip.
        """
        chain = self.chain if chain is None else chain
        errors: List[str] = []
        prev = GENESIS_PREV_HASH
        seen: set = set()
        stakes = dict(self.initial_stakes)
        for i, b in enumerate(chain):
            tag = f"block {i} (step {getattr(b, 'step', '?')})"
            if not isinstance(b, Block):
                errors.append(f"{tag}: not a Block object")
                prev = None
                continue
            try:
                if b.index != i:
                    errors.append(f"{tag}: wrong index")
                if b.prev_hash != prev:
                    errors.append(f"{tag}: broken link to previous block")
                for d in b.transactions:
                    try:
                        t = Transaction(**d)
                    except TypeError as e:
                        errors.append(f"{tag}: malformed transaction ({e})")
                        continue
                    for e in validate_transaction(t):
                        errors.append(f"{tag}: {e}")
                    if t.step != b.step:
                        errors.append(f"{tag}: {t.transaction_id} has step {t.step} != block step")
                    if t.transaction_id in seen:
                        errors.append(f"{tag}: duplicate transaction {t.transaction_id}")
                    seen.add(t.transaction_id)
                if b.merkle_root != merkle_root([tx_hash(d) for d in b.transactions]):
                    errors.append(f"{tag}: merkle root mismatch (transactions modified)")
                if b.compute_hash() != b.block_hash:
                    errors.append(f"{tag}: block hash mismatch (header modified)")
                if b.stake_snapshot != stakes:
                    errors.append(f"{tag}: stake snapshot inconsistent with stake history")
                if b.proposer_id not in self.validators:
                    errors.append(f"{tag}: unknown proposer {b.proposer_id}")
                elif b.proposer_id != self.select_proposer(b.prev_hash, b.stake_snapshot):
                    errors.append(f"{tag}: proposer is not the stake-weighted choice")
                signed = 0.0
                for vid, sig in b.signatures.items():
                    v = self.validators.get(vid)
                    if v is None or not isinstance(sig, str) or not v.check_signature(b.block_hash, sig):
                        errors.append(f"{tag}: invalid signature from {vid}")
                    else:
                        signed += b.stake_snapshot.get(vid, 0.0)
                if not signed > QUORUM_FRACTION * sum(b.stake_snapshot.values()):
                    errors.append(f"{tag}: signatures do not exceed the 2/3 stake quorum")
                if len(b.stake_snapshot) < MIN_VALIDATORS:
                    errors.append(f"{tag}: fewer than {MIN_VALIDATORS} validators")
                if b.proposer_id in stakes:
                    stakes[b.proposer_id] += self.block_reward
            except (TypeError, ValueError, AttributeError, KeyError) as e:
                errors.append(f"{tag}: malformed block ({type(e).__name__}: {e})")
            prev = b.block_hash
        if expected_blocks is not None:
            if len(chain) != len(expected_blocks):
                errors.append(f"chain has {len(chain)} blocks, simulation recorded {len(expected_blocks)}")
            elif chain and chain[-1].block_hash != expected_blocks[-1].block_hash:
                errors.append("chain tip differs from the hash recorded by the simulation")
        return (not errors, errors)

    def transaction_ids(self) -> set:
        return {d["transaction_id"] for b in self.chain for d in b.transactions}

    def tamper_demo(self) -> Tuple[bool, List[str], str]:
        """Modify a COPY of the chain and show that verify_chain() detects it.

        Returns (chain_still_valid, errors, description_of_the_change)."""
        fake = copy.deepcopy(self.chain)
        for b in fake:
            if b.transactions:
                t = b.transactions[0]
                old = t["quantity_kwh"]
                t["quantity_kwh"] = round(old * 10 + 1, 4)
                what = (f"trade {t['transaction_id']} quantity changed {old} -> {t['quantity_kwh']} kWh "
                        f"in block {b.index}")
                break
        else:
            if not fake:
                return (True, [], "chain is empty, nothing to tamper with")
            fake[0].step += 1
            what = "step number of block 0 changed (no trades recorded)"
        ok, errs = self.verify_chain(fake)
        return ok, errs, what

    def to_json(self) -> Dict:
        return {
            "consensus": "Proof-of-Stake (stake-weighted proposer, 2/3 stake signature quorum)",
            "validators": [{"validator_id": v.validator_id, "stake": v.stake, "faulty": v.faulty}
                           for v in self.validators.values()],
            "blocks": [b.to_dict() for b in self.chain],
        }
