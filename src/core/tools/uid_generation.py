import nanoid

def generate_uid(size: int = 10) -> str:
    return str(nanoid.generate(size=size)).strip()
