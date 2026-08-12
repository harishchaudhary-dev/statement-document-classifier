import re
from typing import Dict, Any

class StatementParser:
    @staticmethod
    def parse_fields(text: str, doc_type: str) -> Dict[str, Any]:
        """
        Extracts structured operational metadata using regex patterns based on statement type.
        """
        extracted = {
            "document_type": doc_type,
            "account_number": "N/A",
            "total_amount": "N/A",
            "due_date": "N/A",
            "statement_date": "N/A"
        }

        if not text:
            return extracted

        # General Regex Rules
        account_pattern = r'(?:Account|Card|Policy|Invoice)\s*(?:Number|#|No)?[:\s]*([A-Z0-9\*]{4,18})'
        amount_pattern = r'(?:Balance|Total Due|Amount Due|Total Amount|Payable|Grand Total)[:\s]*\$?\s*([\d,]+\.\d{2})'
        date_pattern = r'(?:Due Date|Statement Date|Date)[:\s]*([\d]{1,2}[\/\.-][\d]{1,2}[\/\.-][\d]{2,4}|[A-Za-z]+\s+\d{1,2},\s+\d{4})'

        acc_match = re.search(account_pattern, text, re.IGNORECASE)
        if acc_match:
            extracted["account_number"] = acc_match.group(1)

        amount_match = re.search(amount_pattern, text, re.IGNORECASE)
        if amount_match:
            extracted["total_amount"] = amount_match.group(1)

        dates = re.findall(date_pattern, text, re.IGNORECASE)
        if dates:
            extracted["statement_date"] = dates[0]
            if len(dates) > 1:
                extracted["due_date"] = dates[1]

        return extracted