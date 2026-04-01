from enterprise.storage.db import ENGINE
from enterprise.storage.models import Base


def init_storage() -> None:
    Base.metadata.create_all(bind=ENGINE)
