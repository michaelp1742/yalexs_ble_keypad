# Yale Access Bluetooth Keypad

A proof of concept, for testers, of a parallel integration to `yalexs_ble`, Home Assistant's
[Yale Access Bluetooth](https://www.home-assistant.io/integrations/yalexs_ble/) integration. It adds three actions
that set, clear, and read the keypad PINs of a Yale lock that Yale Access Bluetooth has loaded, and it keeps each PIN
it sets with a name for the slot. The actions run over Yale Access Bluetooth's connection to the lock. The integration
adds no entity and no device, and changes nothing in Yale Access Bluetooth itself. It reads nothing from the lock's
activity log and sets no `changed_by`.

The actions are the PIN actions of [home-assistant/core#185596](https://github.com/home-assistant/core/pull/185596),
with its action names, fields, and admin rule, in an integration of their own. Each option of the entry turns on one
behavior under test, such as taking the lock's PIN length or slot range from its cloud record. Every option starts off.

## What it adds

Three actions, each for admin users only. Each action targets a Yale Access Bluetooth lock entity, or a device or area
that holds one, and ignores any other entity. A call runs once for each targeted lock, however many of the lock's
entities it reaches. It runs the locks one after another, and the first failure ends the call.

With every option off, a slot is 1 to 250 and a PIN is 4 to 8 digits. The action form takes a slot from 0 to 65535,
and the action refuses a slot outside the lock's range before anything is sent to the lock.

### Set lock credential

`yalexs_ble_keypad.set_lock_credential` writes a PIN to a slot.

| Field | Value |
|---|---|
| `credential_type` | `pin`, the only type |
| `credential_data` | the PIN, in digits |
| `credential_index` | the slot |
| `name` | optional: a name for the slot. Left out or empty, the slot keeps the name this integration has for it. |

Before anything is sent to the lock, the action refuses a slot outside the range, a PIN that is not all digits or not
of the allowed length, and a PIN equal to one that this integration keeps at another slot of the lock, or to one that
the lock's cloud record holds at any slot.

The action then writes the PIN with yalexs-ble's `set_keycode`, which clears the slot and then writes the PIN, valid
at all times. Unless an option below refuses the set, whatever the slot held is replaced, a PIN added in the Yale Home
app included. When the lock has answered every step, the integration keeps the PIN and the slot's name.

When the set fails with `lock_not_running`, or because the lock refused the clear that starts the set, the
integration keeps the slot's record. On any other failure, and when the call is cancelled, it drops the record.

### Clear lock credential

`yalexs_ble_keypad.clear_lock_credential` empties a slot, whether or not this integration set it.

| Field | Value |
|---|---|
| `credential_type` | `pin` |
| `credential_index` | the slot |

The action refuses a slot outside the range before anything is sent, and then clears the slot with yalexs-ble's
`clear_keycode`. When the lock answers, the integration drops the slot's record. When the clear fails with
`lock_not_running`, or because the lock refused it, the integration keeps the record. On any other failure, and when
the call is cancelled, it drops the record.

### Get lock credential status

`yalexs_ble_keypad.get_lock_credential_status` reads a slot from the lock with yalexs-ble's `get_keycode` and returns a
response. It takes `credential_type` and `credential_index`, as the clear does, and refuses a slot outside the range
before anything is sent.

```yaml
action: yalexs_ble_keypad.get_lock_credential_status
target:
  entity_id: lock.front_door
data:
  credential_type: pin
  credential_index: 12
response_variable: slot
```

The response holds one answer for each targeted entity of the lock:

```yaml
lock.front_door:
  credential_exists: true
  name: Cleaner
```

| Key | Value |
|---|---|
| `credential_exists` | `true` when the lock answers that the slot holds a PIN, `false` when the slot is empty |
| `name` | the name this integration keeps for the slot when the slot holds a PIN, otherwise `null` |

The response never holds the PIN.

### Errors

An action that fails raises an error with one of these keys. The action refuses these before anything is sent to the
lock:

| Key | When |
|---|---|
| `no_lock_targeted` | the call targets no Yale Access Bluetooth lock |
| `lock_not_configured` | a targeted lock has no loaded Yale Access Bluetooth Keypad entry |
| `invalid_slot` | the slot is outside the range |
| `master_code_slot` | a set or clear is at the master code's slot |
| `invalid_pin`, `invalid_pin_length` | the PIN is not all digits, or not of the allowed length |
| `pin_in_use` | this integration keeps the PIN at another slot, or the lock's cloud record holds it |
| `no_keypad` | the lock's cloud record shows no keypad |
| `slot_in_use` | the lock's cloud record has a PIN at the slot |

These come from the lock or the connection:

| Key | When |
|---|---|
| `slot_not_empty` | the read before a set found a PIN at a slot where this integration keeps none; nothing is written |
| `pin_already_in_use` | the lock answered `KEYCODE_EXISTING_KEY` (`0x06`) to a step of a set after its clear |
| `keycode_no_space` | the lock answered `KEYCODE_NOSPACE` (`0x07`) to a step of a set after its clear |
| `keycode_timeout` | the lock answered `KEYCODE_TIMEOUT` (`0x08`) to a step of a set after its clear |
| `keycode_slot_in_use` | the lock answered `KEYCODE_SLOT_IN_USE` (`0x45`) to a step of a set after its clear |
| `keycode_error` | the lock refused the clear that starts a set, a clear, or a status read with any answer, or a later step of a set with an answer not listed above |
| `communication_error` | the lock did not answer, or the connection failed |
| `invalid_response` | the lock's answer to a read of a slot held no valid PIN |
| `lock_not_running` | Yale Access Bluetooth's connection to the lock is not running, or was stopped while the command was in flight |

After `pin_already_in_use`, `keycode_no_space`, `keycode_timeout`, or `keycode_slot_in_use`, the slot is empty.
`master_code_slot`, `no_keypad`, `slot_in_use`, and `slot_not_empty` come only with the options below that add them.

## Requirements

- Home Assistant 2026.10.0 or later.
- The Yale Access Bluetooth integration, set up for the lock.
- yalexs-ble from [Yale-Libs/yalexs-ble#424](https://github.com/Yale-Libs/yalexs-ble/pull/424) on, or a release that
  contains it. This integration imports `KeycodeError` and `OperationError` from `yalexs_ble` and calls the lock's
  `get_keycode`, `set_keycode`, and `clear_keycode`. The yalexs-ble that Home Assistant 2026.10 installs, 4.0.1, has
  none of them, and the one that Home Assistant 2026.11 installs, 4.1.2, has no `OperationError` in `yalexs_ble`. With
  either, Home Assistant cannot load this integration and logs an `ImportError`.
- yalexs-ble from #424 requires cryptography 50.0.2 or later. Home Assistant 2026.11 pins cryptography 50.0.2.
  Home Assistant 2026.10 pins cryptography 50.0.1, so on 2026.10 no cryptography version meets both.
- For every check that reads the lock's cloud record, the Yale Home integration, set up for the account that holds the
  lock. These are the check of a PIN against the record's PINs, and the options **PIN rules from the cloud record**,
  **Slot range** set to **Cloud record**, and **Slots in the cloud record are taken**. This integration finds the
  record in Yale Home's loaded entry by the lock's Bluetooth address, and makes no cloud request of its own. Yale Home
  fetches the record when it sets up and then every 24 hours, so a PIN added in the Yale Home app since the last fetch
  is not in it. A record that only the August integration holds is not read. Without a record, these checks refuse
  nothing, and the options take the values they have when off.
- For **PIN rules from the cloud record** and **Slot range** set to **Cloud record**, a yalexs whose `LockDetail` has
  a `capabilities` property, with the lock's capabilities fetched. The yalexs that Home Assistant 2026.10 and 2026.11
  install, 9.2.13, has no such property. Without it, these two options act as if off, and nothing says so.
- At each start, Home Assistant installs the yalexs-ble and yalexs versions that Yale Access Bluetooth and Yale Home
  pin, in place of any other. Other versions stay installed when Home Assistant runs with
  `--skip-pip-packages yalexs-ble,yalexs`, or with `--skip-pip`, which skips the requirements of every integration.

## Installation

With [HACS](https://hacs.xyz/):

1. In HACS, open the menu at the top right and pick **Custom repositories**.
2. Add `https://github.com/Michaelp1742/yalexs_ble_keypad` with the type **Integration**.
3. Find **Yale Access Bluetooth Keypad** in HACS, download it, and restart Home Assistant.

Without HACS, copy `custom_components/yalexs_ble_keypad` into the `custom_components` folder of your Home Assistant
configuration, then restart Home Assistant.

## Setup

1. In **Settings** > **Devices & services**, add **Yale Access Bluetooth Keypad**.
2. Pick the lock. The list shows each lock that Yale Access Bluetooth has loaded and that has no Yale Access Bluetooth
   Keypad entry yet.

The entry takes the title of the lock's Yale Access Bluetooth entry, starts with every option off, and adds no entity.
When Yale Access Bluetooth reloads or unloads the lock's entry, this entry reloads, and it sets up again once Yale
Access Bluetooth has loaded the lock. Removing the entry deletes the PINs and names it keeps; the PINs stay on the lock.

## The options

Each option is in the entry's options, and a change reloads the entry.

**PIN rules from the cloud record.** With the lock's cloud record and its capabilities:

- A PIN is `pinLengthMin` to `pinLengthMax` digits, or else `pinLength` digits, or else 5 digits.
- Every action is refused with `no_keypad` when the record has no `keypad` block and its capabilities do not set
  `integratedKeypad`.
- The master code's slot is the record's `masterPinSlot` when it is above 0, and there is none otherwise.

Without the record or its capabilities, and with the option off, a PIN is 4 to 8 digits, every action is offered, and
the master code's slot is 65518 (`0xFFEE`). Needs Yale Home and a yalexs with the capabilities.

**Slot range.** The range of slots that the three actions take: **1 to 250**, or **Cloud record**, which is
`pinSlotMin` to `pinSlotMax` from the lock's cloud record. **Cloud record** falls back to 1 to 250 when the record's
capabilities lack either value. Needs Yale Home and a yalexs with the capabilities.

**Slots 1 to 65535.** Each action takes any slot from 1 to 65535 in place of the slot range, and the status action can
read the master code's slot. The set and clear actions refuse the master code's slot with `master_code_slot`. Needs
nothing more.

**Status answer.** The status action adds `result` to its answer, and none of these raises an error:

| `result` | The lock's answer |
|---|---|
| `pin` | the slot holds a PIN |
| `empty` | the slot is empty |
| the refusal's name, such as `NACK`, or its value in hex | the lock refused the read |
| `malformed` | the answer held no valid PIN |
| `timeout` | no answer |

`credential_exists` is `null` unless `result` is `pin` or `empty`. A connection that is not running or fails still
raises an error. Needs nothing more.

**Slots in the cloud record are taken.** A set at a slot that any entry of the `pins` block of the lock's cloud record
holds is refused with `slot_in_use`, whatever the entry's state, before anything is sent. Needs Yale Home.

**Read the slot before a set.** Before a set at a slot for which this integration keeps no PIN, the action reads the
slot from the lock and refuses the set with `slot_not_empty` when the lock answers that the slot holds a PIN. A read
that fails fails the set, and nothing is written. A slot for which this integration keeps a PIN is written with no
read. Needs nothing more.

## Where the PIN is kept

- This integration keeps each PIN it sets, with the slot's name, in plain text in
  `.storage/yalexs_ble_keypad.<entry id>.pins` in the Home Assistant configuration folder, and so in Home Assistant's
  backups. Removing the entry deletes the file.
- Home Assistant records each action call, with its data, as a `call_service` event in the recorder's database. The
  PIN of each set is therefore in the database in plain text until the recorder purges the event, after 10 days by
  default (`purge_keep_days`), and in each backup that includes the database. A recorder `exclude` of the event type
  `call_service` keeps every action call out of the database.
- With the `yalexs_ble` logger at debug, yalexs-ble logs each frame it receives from the lock, decrypted, in
  hexadecimal, and the lock's answers to a set and to a status read hold the PIN.

## Icon

The integration's icon is drawn from the lock-smart icon (`mdi-lock-smart`) of Material Design Icons by
[Pictogrammers](https://pictogrammers.com/), which is under the Apache License 2.0.

## Development

```sh
uv venv --python 3.14
uv pip install -r requirements_test.txt
.venv/bin/python -m pytest
.venv/bin/pre-commit run --all-files
```

`requirements_test.txt` installs yalexs-ble and yalexs from local clones at fixed commits, so it resolves only on a
machine that has those clones.
