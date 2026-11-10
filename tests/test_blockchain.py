"""Member 4 - blockchain tests."""
import copy

import pytest

from gridshare.blockchain import MIN_VALIDATORS, Blockchain, merkle_root
from gridshare.contract import AGGREGATOR_ID, Transaction


def tx(i, step=0, buyer="P001", seller="P002", q=1.0, price=0.2, mtype="P2P"):
    return Transaction(f"T{step:03d}-{i:04d}", step, buyer, seller, q, price, mtype)


def filled_chain(steps=5, per_step=4, **kw):
    c = Blockchain(**kw)
    for s in range(steps):
        c.append_transactions(s, [tx(i, s) for i in range(per_step)]
                              + [tx(99, s, buyer="P003", seller=AGGREGATOR_ID, mtype="LOCAL")])
    return c


def test_needs_at_least_10_validators():
    with pytest.raises(ValueError):
        Blockchain(n_validators=MIN_VALIDATORS - 1)
    assert len(Blockchain(n_validators=12).validators) == 12


def test_valid_chain_and_links():
    c = filled_chain()
    ok, errs = c.verify_chain()
    assert ok, errs
    assert len(c.chain) == 5
    for a, b in zip(c.chain, c.chain[1:]):
        assert b.prev_hash == a.block_hash
    assert all(len(b.signatures) == 10 for b in c.chain)


def test_empty_step_still_produces_block():
    c = Blockchain()
    r = c.append_transactions(0, [])
    assert r.n_transactions == 0 and c.verify_chain()[0]


def test_every_transaction_recorded():
    c = filled_chain(steps=3, per_step=7)
    assert len(c.transaction_ids()) == 3 * 8


def test_tamper_transaction_detected():
    c = filled_chain()
    fake = copy.deepcopy(c.chain)
    fake[2].transactions[1]["price_eur_per_kwh"] = 0.01
    ok, errs = c.verify_chain(fake)
    assert not ok and any("merkle" in e for e in errs)
    ok_t, errs_t, what = c.tamper_demo()
    assert ok_t is False and errs_t and "quantity" in what


def test_tamper_header_and_rehash_detected_by_signatures_and_links():
    c = filled_chain()
    fake = copy.deepcopy(c.chain)
    b = fake[1]
    b.transactions[0]["quantity_kwh"] = 50.0
    b.merkle_root = merkle_root([__import__("gridshare.blockchain", fromlist=["tx_hash"]).tx_hash(d)
                                 for d in b.transactions])
    b.block_hash = b.compute_hash()        # attacker recomputes hashes ...
    ok, errs = c.verify_chain(fake)         # ... but signatures and the next link break
    assert not ok
    assert any("signature" in e for e in errs)
    assert any("broken link" in e for e in errs)


def test_forged_signature_detected():
    c = filled_chain()
    fake = copy.deepcopy(c.chain)
    fake[0].signatures["V01"] = "00" * 32
    ok, errs = c.verify_chain(fake)
    assert not ok and any("invalid signature from V01" in e for e in errs)


@pytest.mark.parametrize("bad", [
    tx(1, q=0.0),
    tx(1, q=-1.0),
    tx(1, price=-0.1),
    tx(1, buyer="P001", seller="P001"),
    tx(1, mtype="LOCAL"),                                   # LOCAL without aggregator
    tx(1, seller=AGGREGATOR_ID, mtype="P2P"),               # P2P with aggregator
    tx(1, mtype="SPOT"),
])
def test_invalid_transactions_rejected(bad):
    c = Blockchain()
    with pytest.raises(ValueError):
        c.append_transactions(0, [bad])
    assert c.chain == []


def test_double_spend_rejected():
    c = Blockchain()
    c.append_transactions(0, [tx(1, 0)])
    with pytest.raises(ValueError):
        c.append_transactions(0, [tx(1, 0)])


def test_quorum_with_faulty_validators():
    c = filled_chain(faulty_validators=2)
    ok, errs = c.verify_chain()
    assert ok, errs
    assert all(len(b.signatures) == 8 for b in c.chain)
    with pytest.raises(ValueError, match="quorum"):
        filled_chain(faulty_validators=6)


def test_proposer_deterministic_and_stake_weighted():
    a, b = filled_chain(steps=10), filled_chain(steps=10)
    assert [x.proposer_id for x in a.chain] == [x.proposer_id for x in b.chain]
    assert [x.block_hash for x in a.chain] == [x.block_hash for x in b.chain]
    c = Blockchain()
    for v in c.validators.values():
        v.stake = 1.0
    c.validators["V01"].stake = 1000.0
    picks = [c.select_proposer(f"{i:064x}") for i in range(200)]
    assert picks.count("V01") > 150


def test_proposer_reward_increases_stake():
    c = Blockchain()
    before = {k: v.stake for k, v in c.validators.items()}
    r = c.append_transactions(0, [tx(1)])
    assert c.validators[r.proposer_id].stake == before[r.proposer_id] + c.block_reward


def test_cannot_resign_without_keys():
    """Secrets are random, so knowing the seed is not enough to forge signatures."""
    a, b = Blockchain(seed=42), Blockchain(seed=42)
    assert a.validators["V01"].secret != b.validators["V01"].secret


def test_malformed_transaction_reported_not_crash():
    c = filled_chain()
    fake = copy.deepcopy(c.chain)
    del fake[1].transactions[0]["price_eur_per_kwh"]
    fake[2].transactions[0]["quantity_kwh"] = "5"
    ok, errs = c.verify_chain(fake)
    assert not ok
    assert any("malformed" in e for e in errs)
    assert any("finite" in e for e in errs)


def test_nan_transaction_rejected():
    c = Blockchain()
    with pytest.raises(ValueError):
        c.append_transactions(0, [tx(1, q=float("nan"))])
    with pytest.raises(ValueError):
        c.append_transactions(0, [tx(1, price=float("inf"))])


def test_truncated_chain_detected():
    c = Blockchain()
    recorded = [c.append_transactions(s, [tx(1, s)]) for s in range(6)]
    assert c.verify_chain(expected_blocks=recorded)[0]
    ok, errs = c.verify_chain(c.chain[:-2], expected_blocks=recorded)
    assert not ok and any("blocks" in e for e in errs)


def test_wrong_proposer_or_stake_detected():
    c = filled_chain()
    fake = copy.deepcopy(c.chain)
    others = sorted(set(c.validators) - {fake[3].proposer_id})
    fake[3].proposer_id = others[0]
    ok, errs = c.verify_chain(fake)
    assert not ok and any("proposer" in e for e in errs)
    fake = copy.deepcopy(c.chain)
    fake[4].stake_snapshot["V01"] += 500
    ok, errs = c.verify_chain(fake)
    assert not ok and any("stake" in e for e in errs)


def test_tx_step_mismatch_rejected():
    c = Blockchain()
    with pytest.raises(ValueError):
        c.append_transactions(3, [tx(1, step=2)])


def test_faulty_validators_never_propose():
    c = filled_chain(steps=30, faulty_validators=2)
    faulty = {v.validator_id for v in c.validators.values() if v.faulty}
    assert faulty and not faulty & {b.proposer_id for b in c.chain}


def test_non_block_element_reported():
    c = filled_chain()
    fake = list(c.chain)
    fake[3] = fake[3].to_dict()
    ok, errs = c.verify_chain(fake)
    assert not ok and any("not a Block" in e for e in errs)
