import re
from dataclasses import dataclass, field

from app.pipeline.fetch import MAX_TEXT, Page

SEP = r"[\s\-‐-―()\xa0.]*"
PHONE = re.compile(rf"(?<![\d\w+])(?:\+\s*7|8){SEP}\(?\s*[3489]\d\d(?:{SEP}\d){{7}}(?!\d)")
LOCAL_PHONE = re.compile(rf"(?<![\d\w+])\(\s*[3489]\d{{2,4}}\s*\)(?:{SEP}\d){{5,7}}(?!\d)")
NOT_PHONE_BEFORE = re.compile(r"(инн|кпп|огрн|бик|р/с|к/с|сч[её]т|окпо|оквэд|арт\w*|код)[\s:№.]*$", re.IGNORECASE)
NOT_PHONE_AFTER = re.compile(r"^[ \t]*(руб|р\.|₽|шт|кг|г(?!\.)\b|тыс)", re.IGNORECASE)
EMAIL = re.compile(r"[\w.+-]{1,64}@(?:[\w-]{1,63}\.){1,8}[a-zа-я]{2,24}", re.IGNORECASE)
BAD_EMAIL = re.compile(r"\.(png|jpe?g|gif|webp|svg)$|example\.|sentry|wixpress|domain\.", re.IGNORECASE)
INN = re.compile(r"ИНН(?:\s*/\s*КПП)?[\s:№]*(\d{10}|\d{12})(?!\d)")
MAX_MAIL_LINKS = 20
MAX_EMAIL = 254
ADDRESS = re.compile(
    r"(?:\d{6},\s*)?(?:[А-ЯЁ][а-яё-]+\s+(?:обл\.?|область|край),?\s*)?"
    r"г\.\s*[А-ЯЁ][а-яё-]+(?:-[а-яё]+-[А-ЯЁ][а-яё]+)?,?\s*"
    r"(?:ул\.|улица|пр\.|пр-т|проспект|пер\.|переулок|ш\.|шоссе|тракт|бульвар|б-р|пл\.|площадь|наб\.)"
    r"\s*[^,\n]{2,40}(?:,\s*(?:д\.|дом|стр\.|корп\.|оф\.|офис)?\s*\d+[^,\n]{0,12})*"
)


@dataclass
class Contacts:
    phones: list[str] = field(default_factory=list)
    emails: list[str] = field(default_factory=list)
    inn: str | None = None
    address: str | None = None
    address_local: bool = False


def format_phone(digits: str) -> str:
    return f"+7 {digits[1:4]} {digits[4:7]}-{digits[7:9]}-{digits[9:11]}"


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        digits = "7" + digits
    if len(digits) != 11 or digits[0] not in "78" or digits[1] not in "3489":
        return None
    return format_phone("7" + digits[1:])


def find_phones(text: str) -> list[str]:
    found = []
    for pattern in (PHONE, LOCAL_PHONE):
        for match in pattern.finditer(text):
            if NOT_PHONE_BEFORE.search(text[max(0, match.start() - 16) : match.start()]):
                continue
            if NOT_PHONE_AFTER.search(text[match.end() : match.end() + 6]):
                continue
            phone = normalize_phone(match.group(0))
            if phone and phone not in found:
                found.append(phone)
    return found


def find_emails(text: str) -> list[str]:
    found = []
    for email in EMAIL.findall(text):
        email = email.lower().strip(".")
        if not BAD_EMAIL.search(email) and email not in found:
            found.append(email)
    return found


def inn_valid(inn: str) -> bool:
    digits = [int(c) for c in inn]

    def check(weights: list[int]) -> int:
        return sum(w * d for w, d in zip(weights, digits, strict=False)) % 11 % 10

    if len(inn) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == digits[9]
    return (
        check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == digits[10] and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == digits[11]
    )


def find_inns(text: str) -> list[str]:
    return list(dict.fromkeys(inn for inn in INN.findall(text) if inn_valid(inn)))


def find_addresses(text: str) -> list[str]:
    return [" ".join(m.group(0).split()).rstrip(" ,.") for m in ADDRESS.finditer(text)]


def extract_contacts(pages: list[Page], city_patterns: tuple[str, ...] = ()) -> Contacts:
    contacts = Contacts()
    ordered = sorted(pages, key=lambda p: "contact" not in p.url and "kontakt" not in p.url)
    for page in ordered:
        text = page.text[:MAX_TEXT]
        for raw in page.tel_links:
            phone = normalize_phone(raw)
            if phone and phone not in contacts.phones:
                contacts.phones.append(phone)
        for phone in find_phones(text):
            if phone not in contacts.phones:
                contacts.phones.append(phone)
        mail_links = " ".join(link[:MAX_EMAIL] for link in page.mail_links[:MAX_MAIL_LINKS])
        for email in find_emails(f"{mail_links}\n{text}"):
            if email not in contacts.emails:
                contacts.emails.append(email)
        contacts.inn = contacts.inn or next(iter(find_inns(text)), None)
        for address in find_addresses(text):
            local = any(re.search(p, address.lower().replace("ё", "е")) for p in city_patterns)
            if not contacts.address or (local and not contacts.address_local):
                contacts.address, contacts.address_local = address, local
    contacts.phones = contacts.phones[:5]
    contacts.emails = contacts.emails[:3]
    return contacts
