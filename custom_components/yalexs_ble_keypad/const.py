"""Constants for the Yale Access Bluetooth Keypad integration."""

from enum import StrEnum
import re
from typing import Any, Final

DOMAIN = "yalexs_ble_keypad"
OWNER_DOMAIN = "yalexs_ble"
CLOUD_DOMAIN = "yale"


class YaleXSBLEKeypadService(StrEnum):
    """The keypad PIN actions."""

    CLEAR_LOCK_CREDENTIAL = "clear_lock_credential"
    GET_LOCK_CREDENTIAL_STATUS = "get_lock_credential_status"
    SET_LOCK_CREDENTIAL = "set_lock_credential"


class YaleXSBLEKeypadServiceArgument(StrEnum):
    """The fields of the keypad PIN actions."""

    CREDENTIAL_DATA = "credential_data"
    CREDENTIAL_INDEX = "credential_index"
    CREDENTIAL_TYPE = "credential_type"
    NAME = "name"


CREDENTIAL_TYPE_PIN = "pin"

MIN_PIN_SLOT = 1
MAX_PIN_SLOT = 250
PIN_PATTERN = re.compile(r"[0-9]+")
MIN_PIN_LENGTH = 4
MAX_PIN_LENGTH = 8

# The keycode commands hold the slot in two bytes.
MAX_SLOT = 0xFFFF

# The lowest slot the library's keycode calls take.
MIN_SLOT = 1

# The master code's slot when the cloud record's capabilities are not read.
MASTER_CODE_SLOT = 0xFFEE

# The PIN length the Yale Home and August Home apps take when the cloud record gives none.
DEFAULT_PIN_LENGTH = 5

CONF_SLOT_FIELD_WIDTH = "slot_field_width"
CONF_STATUS_RESULT = "status_result"
CONF_OCCUPANCY_CLOUD_PINS = "occupancy_cloud_pins"
CONF_OCCUPANCY_READ = "occupancy_read"

DEFAULT_OPTIONS: Final[dict[str, Any]] = {
    CONF_SLOT_FIELD_WIDTH: False,
    CONF_STATUS_RESULT: False,
    CONF_OCCUPANCY_CLOUD_PINS: False,
    CONF_OCCUPANCY_READ: False,
}
