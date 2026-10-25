"""Tiny synthetic email builders for the tests."""
from inbox_ledger.parsing import RawMessage


def card(id: str, merchant: str, amount: str = "32.50", date: str = "2026-10-24T12:20:59Z",
         when: str = "24-OCT-2026 04:20 PM", currency: str = "AED") -> RawMessage:
    body = (f"Your NEO VISA Debit Card Card ending with 4021 was used for a purchase of {currency} {amount} "
            f"at {merchant} on {when}. Available limit is AED 2,399.14")
    return RawMessage(id, date, "MashreqAlerts@mashreq.com", "Transaction Confirmation on Mashreq Card", body)


def transfer_receipt(id: str, kind: str = "Local AED", src: str = "3390", amount: str = "70.00",
                     status: str = "Success", date: str = "2026-10-16T13:54:10Z") -> RawMessage:
    if kind == "Own Account":
        mid = (f"From account********{src} * Reference numberMOC0101260000001 * Transaction date2026-10-16 17:54:10 * "
               f"Beneficiary bank countryUNITED ARAB EMIRATES * Beneficiary account Alex Demo ********3390 * ")
        subject = "Own Account Transfer request via Mobile Banking"
    else:
        mid = (f"From Account********{src} * Reference numberMLC0101260000001 * Transaction date2026-10-16 17:54:10 * "
               f"Destination countryUNITED ARAB EMIRATES * To account SARA AHMED *******************0001 * ")
        subject = "Local AED Transfer request via Mobile Banking"
    body = (f"Your money transfer request was processed successfully * Transfer type{kind} * {mid}"
            f"Rate1 AED = 1.00000 AED * Transfer amountAED {amount} * Amount to be debitedAED {amount} * Status{status}")
    return RawMessage(id, date, "MashreqDigital@mashreq.com", subject, body)


def debit_alert(id: str, amount: str = "70.00", account: str = "3390", date: str = "2026-10-16T13:56:10Z",
                short: bool = True) -> RawMessage:
    if short:
        body = (f"Your AC No:XXXXXXXX{account} is debited with AED {amount} for Aani Instant Payments "
                f"(Local IPP Transfer). Login to Online Banking for details")
    else:
        body = (f"Amount of AED {amount} has been debited from your Mashreq account no. XXXXXXXX{account} "
                f"for Account to Account Transfer. Login to Online Banking for details.")
    return RawMessage(id, date, "MashreqAlerts@mashreq.com", "Transaction Notification", body)


def salary(id: str, date: str = "2026-10-01T06:00:00Z") -> RawMessage:
    body = ("Amount of AED 18,500.00 has been credited to your Mashreq account no. XXXXXXXX7710 for Salary. "
            "Login to Online Banking for details.")
    return RawMessage(id, date, "MashreqAlerts@mashreq.com", "Transaction Notification", body)
