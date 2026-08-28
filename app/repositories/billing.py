from app.models import Billing
from app.repositories.base import BaseRepository


class BillingRepository(BaseRepository):
    def add_and_refresh(self, billing: Billing) -> Billing:
        self.add(billing)
        self.commit()
        self.refresh(billing)
        return billing

    def add_and_commit(self, billing: Billing) -> None:
        self.add(billing)
        self.commit()
