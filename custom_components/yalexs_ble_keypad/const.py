"""Constants for the Yale Access Bluetooth Keypad integration."""

from enum import StrEnum

DOMAIN = "yalexs_ble_keypad"
OWNER_DOMAIN = "yalexs_ble"


class YaleXSBLEService(StrEnum):
    """Store keys for Yale Access Bluetooth services."""

    CLEAR_LOCK_CREDENTIAL = "clear_lock_credential"
    GET_LOCK_CREDENTIAL_STATUS = "get_lock_credential_status"
    SET_LOCK_CREDENTIAL = "set_lock_credential"


class YaleXSBLEServiceArgument(StrEnum):
    """Store keys for Yale Access Bluetooth service arguments."""

    CREDENTIAL_DATA = "credential_data"
    CREDENTIAL_INDEX = "credential_index"
    CREDENTIAL_TYPE = "credential_type"
    NAME = "name"


CREDENTIAL_TYPE_PIN = "pin"

MIN_PIN_SLOT = 1
MAX_PIN_SLOT = 250
