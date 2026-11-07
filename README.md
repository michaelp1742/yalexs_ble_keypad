# Yale Access Bluetooth Keypad

A proof of concept, for testers, of a parallel integration to `yalexs_ble`, Home Assistant's
[Yale Access Bluetooth](https://www.home-assistant.io/integrations/yalexs_ble/) integration. It adds three actions
that set, clear, and read the keypad PINs of a Yale lock that Yale Access Bluetooth has loaded, and it keeps each PIN
it sets with a name for the slot. The actions run over Yale Access Bluetooth's connection to the lock. The integration
adds no entity and no device, and changes nothing in Yale Access Bluetooth itself. It reads nothing from the lock's
activity log and sets no `changed_by`.

The actions are the PIN actions of [home-assistant/core#185596](https://github.com/home-assistant/core/pull/185596),
with its action names, fields, and admin rule, in an integration of their own. The actions check a slot and a PIN
against the lock's cloud record, as the Yale Home integration holds it, and a set reads the slot from the lock first.
The entry has one option, **Status answer**, which is on for a new entry.

## What it adds

Three actions, each for admin users only. Each action targets a Yale Access Bluetooth lock entity, or a device or area
that holds one, and ignores any other entity. A call runs once for each targeted lock, however many of the lock's
entities it reaches. It runs the locks one after another, and the first failure ends the call.

The lock's cloud record gives the rules the actions check:

| Rule | From the record | Without the record or its capabilities |
|---|---|---|
| The slot range | `pinSlotMin` to `pinSlotMax`; 1 to 250 when either is missing | 1 to 250 |
| The PIN length | `pinLengthMin` to `pinLengthMax` digits, or else `pinLength` digits, or else 5 digits | 4 to 8 digits |
| The keypad | every action is refused with `no_keypad` when the record has no `keypad` block and its capabilities do not set `integratedKeypad` | every action is offered |
| The master code's slot | `masterPinSlot` when it is above 0, otherwise none | 65518 (`0xFFEE`) |

The action form takes a slot from 0 to 65535, and each action refuses a slot outside the lock's range before anything
is sent to the lock, the master code's slot included when it is outside the range. What each rule needs is under
[Requirements](#requirements).

### Set lock credential

`yalexs_ble_keypad.set_lock_credential` writes a PIN to a slot.

| Field | Value |
|---|---|
| `credential_type` | `pin`, the only type |
| `credential_data` | the PIN, in digits |
| `credential_index` | the slot |
| `name` | optional: a name for the slot, stored with the PIN. Each set replaces the slot's name, so a set that leaves `name` out or empty stores no name, even when the slot had one. |

Before anything is sent to the lock, the action refuses:

- a slot outside the range, and the master code's slot;
- a PIN that is not all digits or not of the allowed length;
- a PIN equal to one that this integration keeps at another slot of the lock, or to one that the lock's cloud record
  holds at any slot (`pin_in_use`);
- a slot that any entry of the `pins` block of the lock's cloud record holds, whatever the entry's state
  (`slot_in_use`).

The action then reads the slot from the lock with yalexs-ble's `get_keycode`. At a slot for which this integration keeps
no PIN, it refuses the set with `slot_not_empty` when the lock answers that the slot holds a PIN. This finds a PIN the
record does not show, such as one added in the Yale Home app since Yale Home last fetched the record. At a slot for
which this integration keeps a PIN, the set goes on when the slot is empty, holds that PIN, or holds the PIN being set,
so a set replaces that PIN in place, and a set retried after one that stopped partway is not refused for its own PIN.
When the slot holds any other PIN, the action refuses the set with `slot_holds_other_pin` and drops the slot's record,
since the slot no longer holds the PIN this integration wrote. A read that fails fails the set, nothing is written, and
the slot's record stays as it was.

The action then writes the PIN with yalexs-ble's `set_keycode`, which clears the slot and then writes the PIN, valid
at all times. When the lock has answered every step, the integration keeps the PIN with the name the call gave, or
with no name when it gave none.

When the write fails with `lock_not_running`, or because the lock refused the clear that starts the set, the integration
keeps the slot's record. On any other failure of the write, and when the call is cancelled while the write runs, it
drops the record.

### Clear lock credential

`yalexs_ble_keypad.clear_lock_credential` empties a slot, whether or not this integration set it.

| Field | Value |
|---|---|
| `credential_type` | `pin` |
| `credential_index` | the slot |

The action refuses a slot outside the range and the master code's slot before anything is sent, and then clears the
slot with yalexs-ble's `clear_keycode`, whatever the slot holds, a PIN added in the Yale Home app included. When the
lock answers, the integration drops the slot's record. When the clear fails with `lock_not_running`, or because the
lock refused it, the integration keeps the record. On any other failure, and when the call is cancelled, it drops the
record.

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
  result: pin
  pin: "482916"
```

| Key | Value |
|---|---|
| `credential_exists` | `true` when the lock answers that the slot holds a PIN, `false` when the slot is empty, and `null` when **Status answer** is on and `result` is neither `pin` nor `empty` |
| `name` | the name this integration keeps for the slot when the slot holds a PIN, otherwise `null` |
| `result` | with **Status answer** on: the result of the read, as in the table under [The option](#the-option) |
| `pin` | with **Status answer** on: the PIN the lock returned for the slot, or `null` when the slot is empty or the read failed |

With **Status answer** off, the response has no `result` and no `pin`, and never holds the PIN. `credential_exists`
is `true` or `false`, and a read that fails raises its error.

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
| `slot_holds_other_pin` | the read before a set found a PIN other than the one this integration keeps at the slot, and other than the PIN being set; nothing is written, and the slot's record is dropped |
| `pin_already_in_use` | the lock answered `KEYCODE_EXISTING_KEY` (`0x06`) to a step of a set after its clear |
| `keycode_no_space` | the lock answered `KEYCODE_NOSPACE` (`0x07`) to a step of a set after its clear |
| `keycode_timeout` | the lock answered `KEYCODE_TIMEOUT` (`0x08`) to a step of a set after its clear |
| `keycode_slot_in_use` | the lock answered `KEYCODE_SLOT_IN_USE` (`0x45`) to a step of a set after its clear |
| `keycode_error` | the lock refused the read before a set, the clear that starts a set, a clear, or a status read with any answer, or a later step of a set with an answer not listed above |
| `communication_error` | the lock did not answer, or the connection failed |
| `invalid_response` | the lock's answer to a read of a slot held no valid PIN |
| `lock_not_running` | Yale Access Bluetooth's connection to the lock is not running, or was stopped while the command was in flight |

After `pin_already_in_use`, `keycode_no_space`, `keycode_timeout`, or `keycode_slot_in_use`, the slot is empty.
`no_keypad` and `slot_in_use` come only with the lock's cloud record. `master_code_slot` comes only where the record's
`masterPinSlot` is inside the slot range in use. Without the record or its capabilities, the master code's slot, 65518,
is outside the range of 1 to 250, and `invalid_slot` refuses it first.

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
  lock. These are the four rules of [What it adds](#what-it-adds), the check of a PIN against the record's PINs, and
  the check of a set's slot against the record's `pins` block. This integration finds the record in Yale Home's loaded
  entry by the lock's Bluetooth address, and makes no cloud request of its own. Yale Home fetches the record when it
  sets up and then every 24 hours, so a PIN added in the Yale Home app since the last fetch is not in it. A record that
  only the August integration holds is not read. Without a record, the two checks against the record's PINs refuse
  nothing, and the four rules take their values without the record.
- For the four rules, a yalexs whose `LockDetail` has a `capabilities` property, with the lock's capabilities fetched.
  The yalexs that Home Assistant 2026.10 and 2026.11 install, 9.2.13, has no such property. Without it, the four rules
  take their values without the record, and nothing says so. The two checks against the record's PINs need only the
  record.
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

The entry takes the title of the lock's Yale Access Bluetooth entry, starts with **Status answer** on, and adds no
entity.
When Yale Access Bluetooth reloads or unloads the lock's entry, this entry reloads, and it sets up again once Yale
Access Bluetooth has loaded the lock. Removing the entry deletes the PINs and names it keeps; the PINs stay on the lock.

## The option

The option is in the entry's options, and a change reloads the entry.

**Status answer.** On for a new entry. The status action adds `result` and `pin` to its answer. `pin` is the PIN the
lock returned, or `null` when `result` is not `pin`. `result` is one of these, and none of them raises an error:

| `result` | The lock's answer |
|---|---|
| `pin` | the slot holds a PIN |
| `empty` | the slot is empty |
| the refusal's name, such as `NACK`, or its value in hex | the lock refused the read |
| `malformed` | the answer held no valid PIN |
| `timeout` | no answer |

`credential_exists` is `null` unless `result` is `pin` or `empty`. A connection that is not running or fails still
raises an error. Off, the status action answers as #185596's does: `credential_exists` and `name`, never the PIN, and
a read that fails raises its error.

An entry made by version 0.1.0 keeps the value of **Status answer** it stored, which 0.1.0 set off for a new entry.
Of the other five options of 0.1.0, four are now the integration's behavior and **Slots 1 to 65535** is gone, since no
action goes past the slot range. The values such an entry stored for the five are not read.

## Where the PIN is kept

- This integration keeps each PIN it sets, with the slot's name, in plain text in
  `.storage/yalexs_ble_keypad.<entry id>.pins` in the Home Assistant configuration folder, and so in Home Assistant's
  backups. Removing the entry deletes the file.
- Home Assistant records each action call, with its data, as a `call_service` event in the recorder's database. The
  PIN of each set is therefore in the database in plain text until the recorder purges the event, after 10 days by
  default (`purge_keep_days`), and in each backup that includes the database. A recorder `exclude` of the event type
  `call_service` keeps every action call out of the database.
- With **Status answer** on, the status action's response holds the PIN of the slot it reads, so the PIN is in any
  automation or script variable that holds the response, and in a trace that records it.
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
