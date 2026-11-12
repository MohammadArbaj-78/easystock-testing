"""Store settings service.

"Asli qty save karo" (save_real_qty): decides what quantity an invoice
scan saves to stock.
  - ON  : the quantity on the invoice (+ free) is saved, as always.
  - OFF : every scanned medicine is saved with quantity 0 - name, pack,
          batch, expiry, MRP, rate etc. are all still saved. For stores
          that only scan invoices for now and are not selling yet.
A store that never touched the switch counts as ON (the original
behaviour), so nothing changes for anyone until they switch it off.
"""

import logging

from modules.store_settings import repository as settings_repository

logger = logging.getLogger(__name__)


def invoice_saves_real_quantity(store_id: int) -> bool:
    """True if invoice scans should save the real quantity. Never raises:
    if the setting cannot be read, the real quantity is saved (the
    original behaviour) rather than silently zeroing stock."""
    try:
        value = settings_repository.get_save_real_qty(store_id)
    except Exception as exc:
        logger.warning("Could not read the 'save real quantity' setting: %s", exc)
        return True
    return True if value is None else bool(value)


def set_invoice_saves_real_quantity(store_id: int, value: bool) -> None:
    """Remember the switch for this store (kept across logins/restarts)."""
    settings_repository.set_save_real_qty(store_id, bool(value))