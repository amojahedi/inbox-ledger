"""Every bank profile against synthetic alerts (invented merchants, names and digits)."""
from pathlib import Path

import pytest

from inbox_ledger.config import DEFAULTS
from inbox_ledger.parsing import RawMessage, find_mirrors, load_bank, load_banks, parse_message

BANK_DIR = DEFAULTS / "banks"
DATE = "2026-10-20T12:15:00Z"  # 16:15 in Dubai


def mail(sender: str, subject: str, body: str, date: str = DATE) -> RawMessage:
    return RawMessage("t1", date, sender, subject, body)


ENBD_ACCT_SUBJECT = "Transaction advice for your account ending with 8642"
ENBD_TRANSFER = ("Dear Sam Example, Here is a consolidated status of your {kind}. Transaction Date: {when} "
                 "From Account: 012***34***56 Debit Amount: AED 4,321.00 Transaction Amount: AED 4,321.00 "
                 "Exchange Rate: N/A Beneficiary Name: {who} Beneficiary Account / IBAN: AE070331234567890123456 "
                 "Status: {status}")

# (id, sender, subject, body, expected bank, expected fields)
CASES = [
    # ---- Emirates NBD
    ("enbd-atm", "alert@emiratesnbd.com", ENBD_ACCT_SUBJECT,
     "Dear Customer, AED 12,750.00 has been withdrawn from your account 012XXX34XXX56. The available balance is "
     "AED 1,000.00. Save queuing time by using our free ATMs 24 x 7.",
     "Emirates NBD", dict(kind="account_debit", direction="out", amount=12750.0, currency="AED", account="8642",
                          merchant_raw="ATM / cash withdrawal", occurred_at="2026-10-20T16:15")),
    ("enbd-deducted", "alert@emiratesnbd.com", ENBD_ACCT_SUBJECT,
     "Dear Customer, AED 2,340.00 has been deducted from your account 012XXX34XXX56 for issuance of "
     "Telegraphic Transfer. The available balance is AED 900.00.",
     "Emirates NBD", dict(kind="account_debit", direction="out", amount=2340.0, account="8642",
                          merchant_raw="issuance of Telegraphic Transfer")),
    ("enbd-credit", "alert@emiratesnbd.com", ENBD_ACCT_SUBJECT,
     "Dear Customer, AED 18,500.00 has been credited to your account 012XXX34XXX56 for Salary.",
     "Emirates NBD", dict(kind="account_credit", direction="in", amount=18500.0, account="8642",
                          merchant_raw="Salary")),
    ("enbd-credit-no-currency", "alert@emiratesnbd.com", ENBD_ACCT_SUBJECT,
     "Dear Customer, 400.00 has been deposited into your account 012XXX34XXX56.",
     "Emirates NBD", dict(kind="account_credit", direction="in", amount=400.0, currency="AED", account="8642")),
    ("enbd-local-transfer", "OnlineBanking@emiratesnbd.com", "Local Bank Transfer",
     ENBD_TRANSFER.format(kind="Local Bank Transfer", when="07/Jan/2026 03:14 PM", who="Jane Example Beneficiary",
                          status="Success"),
     "Emirates NBD", dict(kind="transfer", direction="out", amount=4321.0, currency="AED", account="56",
                          counterparty="Jane Example Beneficiary", status="Success",
                          occurred_at="2026-01-07T15:14")),
    ("enbd-own-transfer", "OnlineBanking@emiratesnbd.com", "Own Account Transfer",
     ENBD_TRANSFER.format(kind="Own Account Transfer", when="08/Jan/2026 09:05 AM", who="Sam Example",
                          status="Success"),
     "Emirates NBD", dict(kind="transfer", direction="internal", amount=4321.0, counterparty="Sam Example",
                          occurred_at="2026-01-08T09:05")),
    ("enbd-card", "alert@emiratesnbd.com", "Card transaction alert",
     "Dear Customer, Purchase of AED 45.50 with Debit Card ending 7391 at CAFE LUNA DUBAI AE on 12-Oct-2026 "
     "04:11 PM. Avl Bal AED 2,100.00",
     "Emirates NBD", dict(kind="card_purchase", direction="out", amount=45.5, currency="AED", account="7391",
                          merchant_raw="CAFE LUNA DUBAI AE", occurred_at="2026-10-12T16:11")),
    # ---- Liv
    ("liv-credit", "notifications@liv.me", "Transaction advice for your account ending with 5520",
     "AED 250.00 has been credited to your account 011XXX20XXX33.",
     "Liv", dict(kind="account_credit", direction="in", amount=250.0, account="5520")),
    ("liv-debit", "notifications@liv.me", "Transaction advice for your account ending with 5520",
     "AED 38.00 has been debited from your account 011XXX20XXX33 for Kebab Corner.",
     "Liv", dict(kind="account_debit", direction="out", amount=38.0, account="5520", merchant_raw="Kebab Corner")),
    # ---- ADIB (public examples)
    ("adib-purchase", "alerts@adib.ae", "Purchase Transaction Alert",
     "Purchase Transaction Alert Dear Customer, Transaction of AED 73.40 debited from your a/c *123 at "
     "SAMPLE STORE1 DU BAI AE. Avl Bal is AED 4,321.09 Yours Sincerely, Abu Dhabi Islamic Bank",
     "ADIB", dict(kind="card_purchase", direction="out", amount=73.4, currency="AED", account="123",
                  merchant_raw="SAMPLE STORE1 DU BAI AE")),
    ("adib-purchase-usd", "alerts@adib.ae", "Purchase Transaction Alert",
     "Transaction of USD25.00 debited from your a/c *4321 at ACME.COM NEW YORK US. Avl Bal is AED 1.00",
     "ADIB", dict(kind="card_purchase", amount=25.0, currency="USD", account="4321",
                  merchant_raw="ACME.COM NEW YORK US")),
    ("adib-debit", "alerts@adib.ae", "Debit Transaction Alert",
     "Debit Transaction Alert Dear Customer, AED 41.25 was debited from your account *456. Your available account "
     "balance is AED 1,234.56 Yours Sincerely, Abu Dhabi Islamic Bank",
     "ADIB", dict(kind="account_debit", direction="out", amount=41.25, account="456")),
    ("adib-credit", "alerts@adib.ae", "Credit Transaction Alert",
     "Dear Customer, AED 12,750.00 was credited to your account *4567. Your available account balance is AED 1.00",
     "ADIB", dict(kind="account_credit", direction="in", amount=12750.0, account="4567")),
    # ---- Dubai Islamic Bank (public examples, Arabic first)
    ("dib-card", "DIB.notification@dib.ae", "DIB Notification",
     "إشعار مشتريات المبلغ AED 250.00 بتاريخ 05-06-2026 الدفع الى CARREFOUR DUBAI رقم البطاقة XXXX1234",
     "Dubai Islamic Bank", dict(kind="card_purchase", direction="out", amount=250.0, currency="AED", account="1234",
                                merchant_raw="CARREFOUR DUBAI", occurred_at="2026-10-20T16:15")),
    ("dib-reversal", "DIB.notification@dib.ae", "DIB Notification",
     "عزيزي المتعامل, A transaction to the value of AED 52.00 made at SAMPLE SHOP LLC on your DIB card ending with "
     "XX1234 has been reversed. مع اطيب التحيات، بنك دبي الإسلامي",
     "Dubai Islamic Bank", dict(kind="card_purchase", direction="in", amount=52.0, account="1234",
                                merchant_raw="SAMPLE SHOP LLC")),
    ("dib-refund", "DIB.notification@dib.ae", "DIB Notification",
     "عزيزي المتعامل, تم إرجاع مبلغ 1,234.50 درهم على بطاقة بنك دبي الإسلامي الخاصة بك والمنتهية بالرقم XX1234. "
     "مع اطيب التحيات، بنك دبي الإسلامي",
     "Dubai Islamic Bank", dict(kind="card_purchase", direction="in", amount=1234.5, currency="AED", account="1234")),
    ("dib-salary", "DIB.notification@dib.ae", "DIB Notification",
     "إشعار إيداع المبلغ AED 9,250.75 بتاريخ 05-06-2026 المعاملة SALARY TRNSFER من حساب 0123456789",
     "Dubai Islamic Bank", dict(kind="account_credit", direction="in", amount=9250.75, account="6789",
                                merchant_raw="SALARY TRNSFER")),
    ("dib-withdrawal", "DIB.notification@dib.ae", "DIB Notification",
     "إشعار سحب المبلغ AED 100.00 بتاريخ 05-06-2026 المعاملة ATM من حساب 0123456789",
     "Dubai Islamic Bank", dict(kind="account_debit", direction="out", amount=100.0, account="6789",
                                merchant_raw="ATM")),
    ("dib-own-transfer", "DIB.notification@dib.ae", "DIB Notification",
     "تحويل الأموال عزيزي المتعامل, إشعار تحويل الأموال بين حساباتك بتاريخ 05-06-2026 07:41 بالتفاصيل التالية. "
     "المبلغ (يشمل 5% ضريبة القيمة المضافة) AED 4321.09 من حساب 001-000-123XXXX01 [From Account FRM] الى "
     "001-000-123XXXX02 الحالة تمت بنجاح الرقم المرجعي [Reference Number] مع اطيب التحيات، بنك دبي الإسلامي",
     "Dubai Islamic Bank", dict(kind="transfer", direction="internal", amount=4321.09, account="01")),
    ("dib-bank-transfer", "DIB.notification@dib.ae", "DIB Notification",
     "تحويل الأموال عزيزي المتعامل, إشعار تحويل الأموال الى بنك آخر داخل الدولة بتاريخ 05-06-2026 07:41 "
     "بالتفاصيل التالية. المبلغ AED 800.00 من حساب 001-000-123XXXX01 الى AE000000000000000000001 "
     "البنك المستفيد sample bank uae الحالة تمت بنجاح الرقم المرجعي [Reference Number]",
     "Dubai Islamic Bank", dict(kind="transfer", direction="out", amount=800.0, counterparty="sample bank uae")),
    ("dib-money-transfer", "DIB.notification@dib.ae", "DIB Notification",
     "Money Transfer Dear Customer, This is to notify you that a Domestic Fund Transfer transaction has been "
     "initiated on 07-23-2026 11:12:13 with the following details. Amount 1,234.56 From AE0000000000000XXXXX101 "
     "To AE0000000000000XXXXX002 Beneficiary Bank Sample Bank PJSC Status Credited to beneficiary "
     "Reference Number [Reference Number] Best Regards, Dubai Islamic Bank",
     "Dubai Islamic Bank", dict(kind="transfer", direction="out", amount=1234.56, currency="AED", account="101",
                                counterparty="Sample Bank PJSC")),
    # ---- Emirates Islamic (sample push messages published by the bank)
    ("ei-pos", "alerts@emiratesislamic.ae", "Transaction alert",
     "AED 1,800.00 has been deducted from your account 0015-123456-001 as POS transaction. Visit www.emiratesislamic.ae",
     "Emirates Islamic", dict(kind="card_purchase", direction="out", amount=1800.0, account="001")),
    ("ei-credit-card", "alerts@emiratesislamic.ae", "Transaction alert",
     "AED 200.00 has been debited from your Credit/Charge Card at EMV TEST POS TERMINAL, DUBAI. Thank You",
     "Emirates Islamic", dict(kind="card_purchase", direction="out", amount=200.0,
                              merchant_raw="EMV TEST POS TERMINAL, DUBAI")),
    ("ei-atm", "alerts@emiratesislamic.ae", "Transaction alert",
     "AED 1,700.00 has been withdrawn from your account 0015-123456-001 as ATM transaction. The available "
     "balance of your account is AED 5,000.00",
     "Emirates Islamic", dict(kind="account_debit", direction="out", amount=1700.0, merchant_raw="ATM withdrawal")),
    ("ei-deposit", "alerts@emiratesislamic.ae", "Transaction alert",
     "AED 1,000.00 has been deposited to your account 0015-123456-001 through the deposit machine. Visit "
     "www.emiratesislamic.ae",
     "Emirates Islamic", dict(kind="account_credit", direction="in", amount=1000.0, account="001",
                              merchant_raw="deposit machine")),
    ("ei-telex", "alerts@emiratesislamic.ae", "Transaction alert",
     "USD 1,500.00 has been received as TELEGRAPHIC TRANSFER. The available balance of your account is AED 1.00",
     "Emirates Islamic", dict(kind="account_credit", direction="in", amount=1500.0, currency="USD",
                              merchant_raw="TELEGRAPHIC TRANSFER")),
    # ---- ADCB (inferred wording)
    ("adcb-card", "alerts@adcb.com", "Card transaction",
     "Dear Customer, your ADCB Credit Card ending 3321 was used for a purchase of AED 1,232.50 at GOLDEN KEBAB "
     "DUBAI AE on 14/10/2026 21:05. Available limit AED 4,000.00",
     "ADCB", dict(kind="card_purchase", direction="out", amount=1232.5, currency="AED", account="3321",
                  merchant_raw="GOLDEN KEBAB DUBAI AE", occurred_at="2026-10-14T21:05")),
    ("adcb-debit-account", "notification@adcb.com", "Account alert",
     "AED 5,000.00 has been debited from your account no. XXXXXXXX9917 for Rent payment.",
     "ADCB", dict(kind="account_debit", direction="out", amount=5000.0, account="9917", merchant_raw="Rent payment")),
    ("adcb-ac-credited", "notification@adcb.com", "Account alert",
     "Your AC No: XXXXXXXX9917 is credited with AED 14,000.00 for Salary.",
     "ADCB", dict(kind="account_credit", direction="in", amount=14000.0, account="9917", merchant_raw="Salary")),
    # ---- FAB (inferred wording)
    ("fab-card", "alerts@bankfab.com", "Card alert",
     "Purchase of AED 89.00 using your FAB Debit Card ending 5543 at ZARA HOME DUBAI AE on 03-Oct-2026 06:30 PM.",
     "FAB", dict(kind="card_purchase", direction="out", amount=89.0, account="5543",
                 merchant_raw="ZARA HOME DUBAI AE", occurred_at="2026-10-03T18:30")),
    ("fab-credit", "alerts@bankfab.com", "Account alert",
     "AED 3,000.00 has been credited to your account XXXX4410.",
     "FAB", dict(kind="account_credit", direction="in", amount=3000.0, account="4410")),
    ("fab-refund", "alerts@bankfab.com", "Card alert",
     "A refund of AED 120.00 has been credited to your card ending 5543 from PLAZA SHOES DUBAI AE",
     "FAB", dict(kind="card_purchase", direction="in", amount=120.0, account="5543",
                 merchant_raw="PLAZA SHOES DUBAI AE")),
    # ---- RAKBANK (inferred wording)
    ("rak-card", "alerts@rakbank.ae", "Card transaction",
     "AED 64.75 was spent on your RAKBANK Debit Card ending 8802 at LITTLE BAKERY AJMAN AE on 02-OCT-2026 11:20",
     "RAKBANK", dict(kind="card_purchase", direction="out", amount=64.75, account="8802",
                     merchant_raw="LITTLE BAKERY AJMAN AE", occurred_at="2026-10-02T11:20")),
    ("rak-card-used", "notifications@rakbank.ae", "Card transaction",
     "Your RAKBANK Credit Card ending 1180 has been used for AED 310.00 at NORTHSIDE MART RAS AL KHAIMAH AE.",
     "RAKBANK", dict(kind="card_purchase", amount=310.0, account="1180", merchant_raw="NORTHSIDE MART RAS AL KHAIMAH AE")),
    ("rak-debit", "alerts@rakbank.ae", "Account alert",
     "AED 900.00 has been debited from your account ending 6612 for Standing instruction.",
     "RAKBANK", dict(kind="account_debit", direction="out", amount=900.0, account="6612",
                     merchant_raw="Standing instruction")),
    # ---- Commercial Bank of Dubai (inferred wording)
    ("cbd-card", "alerts@cbd.ae", "Card transaction",
     "Purchase of AED 150.00 with Credit Card ending 2207 at TECH BAZAAR DUBAI AE on 09-Oct-2026 02:15 PM. "
     "Available limit is AED 9,000.00",
     "Commercial Bank of Dubai", dict(kind="card_purchase", direction="out", amount=150.0, account="2207",
                                      merchant_raw="TECH BAZAAR DUBAI AE", occurred_at="2026-10-09T14:15")),
    ("cbd-txn", "alerts@cbd.ae", "Card transaction",
     "Txn of USD 12.99 on card ending 2207 at STREAMBOX.COM LONDON GB",
     "Commercial Bank of Dubai", dict(kind="card_purchase", amount=12.99, currency="USD", account="2207",
                                      merchant_raw="STREAMBOX.COM LONDON GB")),
    ("cbd-credit", "alerts@cbd.ae", "Account alert",
     "AED 7,500.00 has been credited to your account number 100200302207 for Salary.",
     "Commercial Bank of Dubai", dict(kind="account_credit", direction="in", amount=7500.0, account="2207",
                                      merchant_raw="Salary")),
    # ---- Wio (inferred wording)
    ("wio-spend", "no-reply@wio.io", "You spent AED 25.00",
     "You spent AED 25.00 at SUNRISE JUICE BAR DUBAI AE using your Wio Debit Card.",
     "Wio", dict(kind="card_purchase", direction="out", amount=25.0, currency="AED",
                 merchant_raw="SUNRISE JUICE BAR DUBAI AE")),
    ("wio-received", "no-reply@wio.io", "Money received",
     "You've received AED 500.00 from Priya Example.",
     "Wio", dict(kind="account_credit", direction="in", amount=500.0, merchant_raw="Priya Example")),
    ("wio-sent", "no-reply@wio.io", "Money sent",
     "You sent AED 75.00 to Daniel Example.",
     "Wio", dict(kind="transfer", direction="out", amount=75.0, counterparty="Daniel Example")),
]


@pytest.mark.parametrize("sender,subject,body,bank,expected", [c[1:] for c in CASES], ids=[c[0] for c in CASES])
def test_profile_samples(banks, sender, subject, body, bank, expected):
    t = parse_message(mail(sender, subject, body), banks)
    assert t is not None, "sample was not recognised"
    assert t.bank == bank
    assert not t.pattern.startswith("generic_")
    for field, value in expected.items():
        assert getattr(t, field) == value, field


def test_every_bank_has_samples(banks):
    covered = {c[4] for c in CASES} | {"Mashreq", "Any bank"}
    assert {b.name for b in banks} == covered


def test_enbd_failed_transfer_is_ignored(banks):
    body = ENBD_TRANSFER.format(kind="Local Bank Transfer", when="07/Jan/2026 03:14 PM", who="X Y", status="Failed")
    assert parse_message(mail("OnlineBanking@emiratesnbd.com", "Local Bank Transfer", body), banks) is None


def test_enbd_account_alert_without_subject_has_no_account(banks):
    t = parse_message(mail("alert@emiratesnbd.com", "Fwd: alert", "AED 10.00 has been debited from your account 012XXX34XXX56."), banks)
    assert t.account == "" and t.amount == 10.0


def test_enbd_alert_mirrors_transfer_despite_different_account_format(banks):
    transfer = parse_message(mail("OnlineBanking@emiratesnbd.com", "Local Bank Transfer", ENBD_TRANSFER.format(
        kind="Local Bank Transfer", when="20/Oct/2026 04:14 PM", who="Jane Example", status="Success")), banks)
    transfer.id = "tr"
    advice = parse_message(RawMessage("t2", "2026-10-20T12:16:00Z", "alert@emiratesnbd.com", ENBD_ACCT_SUBJECT,
                                      "AED 4,321.00 has been deducted from your account 012XXX34XXX56."), banks)
    other = parse_message(RawMessage("t3", "2026-10-20T12:17:00Z", "alert@emiratesnbd.com", ENBD_ACCT_SUBJECT,
                                     "AED 99.00 has been deducted from your account 012XXX34XXX56."), banks)
    assert find_mirrors([transfer, advice, other], banks) == {advice.id: "tr"}


@pytest.mark.parametrize("amount,expected", [(".50", 0.5), ("1,000.00", 1000.0), ("12", 12.0), ("7.5", 7.5)])
def test_amount_shapes(banks, amount, expected):
    body = f"Purchase of AED {amount} with Debit Card ending 7391 at TEST SHOP DUBAI AE"
    assert parse_message(mail("alert@emiratesnbd.com", "x", body), banks).amount == expected


@pytest.mark.parametrize("card", ["Card ending 7391", "Card ending with 7391", "card XXXX7391", "Card no. XXXXXXXXXXXX7391"])
def test_card_digit_shapes(banks, card):
    body = f"Purchase of AED 20.00 with Debit {card} at TEST SHOP DUBAI AE"
    assert parse_message(mail("alert@emiratesnbd.com", "x", body), banks).account == "7391"


# ---- generic fallback ----------------------------------------------------------------------

GENERIC_CASES = [
    ("alerts@examplebank.com", "purchase of AED 12.34 at BLUE MOON CAFE DUBAI AE on 15/10/2026 10:30.",
     dict(kind="card_purchase", direction="out", amount=12.34, currency="AED", merchant_raw="BLUE MOON CAFE DUBAI AE",
          occurred_at="2026-10-15T10:30")),
    ("notifications@examplebank.ae", "Your card ending 4455 was used for a purchase of USD 9.99 at PIXEL STORE.",
     dict(kind="card_purchase", currency="USD", amount=9.99, account="4455", merchant_raw="PIXEL STORE")),
    ("alert@examplebank.com", "You have spent AED 45.00 at GREEN GROCER using card ending 1020",
     dict(kind="card_purchase", direction="out", amount=45.0, account="1020", merchant_raw="GREEN GROCER")),
    ("noreply@examplebank.com", "AED 80.00 was spent on your card ending 7766 at LOCAL PHARMACY. Available balance AED 5.00",
     dict(kind="card_purchase", amount=80.0, account="7766", merchant_raw="LOCAL PHARMACY")),
    ("alerts@examplebank.com", "AED 250.00 has been debited from your account XXXX3030 for Utility bill payment.",
     dict(kind="account_debit", direction="out", amount=250.0, account="3030", merchant_raw="Utility bill payment")),
    ("alerts@examplebank.com", "AED 250.00 has been debited from your account XXXX3030.",
     dict(kind="account_debit", amount=250.0, account="3030", merchant_raw="Account debit")),
    ("alerts@examplebank.com", "Your A/C XXXX3030 is debited with AED 99.00 for Online purchase.",
     dict(kind="account_debit", amount=99.0, account="3030", merchant_raw="Online purchase")),
    ("alerts@examplebank.com", "Your A/C XXXX3030 is credited with AED 1,500.00 for Salary credit.",
     dict(kind="account_credit", direction="in", amount=1500.0, account="3030", merchant_raw="Salary credit")),
    ("alerts@examplebank.com", "AED 4,000.00 has been credited to your account XXXX3030.",
     dict(kind="account_credit", direction="in", amount=4000.0, account="3030")),
    ("noreply@examplebank.com", "Txn of AED 15.00 on card ending 8080 at CAR WASH EXPRESS on 01-Oct-2026 08:05 AM",
     dict(kind="card_purchase", amount=15.0, account="8080", merchant_raw="CAR WASH EXPRESS",
          occurred_at="2026-10-01T08:05")),
    ("alerts@examplebank.com", "A transaction of AED 33.00 was made at OLIVE GARDEN with card ending 6060.",
     dict(kind="card_purchase", amount=33.0, account="6060", merchant_raw="OLIVE GARDEN")),
    ("alerts@examplebank.com", "Refund of AED 60.00 has been credited to your card ending 6060 from SHOE PALACE.",
     dict(kind="card_purchase", direction="in", amount=60.0, account="6060", merchant_raw="SHOE PALACE")),
    ("alerts@examplebank.com", "You have transferred AED 300.00 to Maya Example from your account XXXX3030.",
     dict(kind="transfer", direction="out", amount=300.0, counterparty="Maya Example")),
    ("alerts@hsbc.com", "Purchase of GBP 18.20 at CORNER BOOKS LONDON GB",
     dict(kind="card_purchase", currency="GBP", amount=18.2, merchant_raw="CORNER BOOKS LONDON GB")),
    ("alerts@examplebank.com", "Dear Customer, a purchase of AED 12.34 was made at MERCH ONE on your card ending 1234.",
     dict(kind="card_purchase", amount=12.34, account="1234", merchant_raw="MERCH ONE")),
    ("alerts@examplebank.com", "Purchase of AED 50.00 at SHOP ONE. Never share your OTP with anyone.",
     dict(kind="card_purchase", amount=50.0, merchant_raw="SHOP ONE")),
]


@pytest.mark.parametrize("sender,body,expected", GENERIC_CASES)
def test_generic_fallback(banks, sender, body, expected):
    t = parse_message(mail(sender, "Transaction alert", body), banks)
    assert t is not None
    assert t.bank == "Any bank" and t.pattern.startswith("generic_")
    for field, value in expected.items():
        assert getattr(t, field) == value, field


@pytest.mark.parametrize("sender", ["promo@examplebank.com", "alerts@shop.example.com", "someone@gmail.com",
                                    "alerts@bankruptcy-news.org", "newsletter@examplebank.com"])
def test_generic_ignores_non_alert_senders(banks, sender):
    assert parse_message(mail(sender, "x", "Purchase of AED 12.34 at BLUE MOON CAFE"), banks) is None


@pytest.mark.parametrize("body", [
    "Use OTP 123456 to authorize transaction of AED 50.00 at SHOP ONE",
    "123456 is your OTP for purchase of AED 50.00 at SHOP ONE",
    "Your transaction of AED 50.00 at SHOP ONE was declined due to insufficient funds",
    "Get cashback of AED 50 at partner stores",
    "Payment of AED 1,000.00 is due on 5 Nov",
])
def test_generic_ignores_otp_declined_and_promos(banks, body):
    assert parse_message(mail("alerts@examplebank.com", "x", body), banks) is None


def test_generic_ignores_unrelated_text(banks):
    assert parse_message(mail("alerts@examplebank.com", "x", "Your statement is ready. Pay AED 100 by 5 Nov."), banks) is None


def test_specific_profile_wins_over_generic(banks):
    from .helpers import card
    t = parse_message(card("m1", "CAREEM FOOD DUBAI AE"), banks)
    assert t.bank == "Mashreq" and t.pattern == "card_purchase"
    t = parse_message(mail("alerts@emiratesnbd.com", "x", "Purchase of AED 12.34 at BLUE MOON CAFE DUBAI AE"), banks)
    assert t.bank == "Emirates NBD"


def test_generic_catches_what_a_bank_profile_misses(banks):
    """A known bank's unfamiliar wording still falls through to the fallback."""
    t = parse_message(mail("alerts@adcb.com", "x", "Payment of AED 70.00 at DESERT GEAR SHOP made with your card."), banks)
    assert t.bank == "Any bank" and t.amount == 70.0


def test_user_profile_is_tried_before_the_fallback(tmp_path):
    (tmp_path / "mybank.yaml").write_text(
        "name: My Bank\nsenders: ['examplebank\\.com$']\ntimezone: UTC\npatterns:\n"
        "  - {name: mine, kind: card_purchase, direction: out, regex: 'Paid (?P<amount>[\\d.]+) at (?P<merchant>[A-Z ]+)'}\n")
    banks = load_banks(DEFAULTS / "banks", tmp_path)
    assert banks[-1].fallback and banks[-1].name == "Any bank"
    t = parse_message(mail("alerts@examplebank.com", "x", "Paid 12.50 at LOCAL SHOP"), banks)
    assert t.bank == "My Bank" and t.pattern == "mine"


# ---- profile files -------------------------------------------------------------------------

@pytest.mark.parametrize("path", sorted(BANK_DIR.glob("*.yaml")), ids=lambda p: p.stem)
def test_profile_loads_and_is_well_formed(path: Path):
    bank = load_bank(path)
    assert bank.name and bank.patterns and bank.senders and bank.gmail_query is not None
    assert bank.status in {"verified", "beta"}
    assert all(p.kind in {"card_purchase", "account_debit", "account_credit", "transfer"} for p in bank.patterns)
    assert all(p.direction in {"in", "out", "internal"} for p in bank.patterns)
    assert all("amount" in p.regex.groupindex for p in bank.patterns)
    assert len({p.name for p in bank.patterns}) == len(bank.patterns)
    if bank.status == "beta":
        assert "Status: beta" in path.read_text()


def test_generic_profile_is_marked(banks):
    generic = next(b for b in banks if b.fallback)
    assert generic.name == "Any bank" and all(p.name.startswith("generic_") for p in generic.patterns)
    assert sum(b.fallback for b in banks) == 1 and banks[-1] is generic


def test_mashreq_is_verified(banks):
    assert next(b for b in banks if b.name == "Mashreq").status == "verified"
