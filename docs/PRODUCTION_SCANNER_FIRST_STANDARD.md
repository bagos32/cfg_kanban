# CFG Kanban Production Scanner-First Standard

## Purpose

Production operators must be able to complete routine floor work with a fixed keyboard-wedge barcode
scanner while wearing gloves or working with wet, oily, or occupied hands. Every Production Kanban
feature is therefore designed as scanner-first and touch-capable. A production feature is not complete
when its only entry point is a screen button.

## Required delivery contract

Every new or adjusted production-floor action must include all of the following in the same package:

1. A stable, namespaced `CFG:CMD:*` payload that opens or performs the action in the currently loaded
   Card context.
2. Context validation on the server and client. The command must reject unavailable, unauthorized, or
   unsafe work instead of guessing.
3. Numbered selection with `CFG:SELECT:1` through `CFG:SELECT:10` when more than one safe Work Order,
   Job Card, operation, material row, or bin is eligible.
4. Scanner handling inside every dialog opened by the command, including applicable quantity, physical
   identity, confirmation, cancellation, and dismissal scans.
5. Focus recovery after success, validation failure, error popup, cancellation, and dialog closure.
6. A selectable entry in **Scanner Help → Print Command Labels**, including a clear standard label that
   may be supplemented by a custom or translated print label.
7. Scanner Help and User Manual documentation showing the exact payload and scan order.
8. Automated contract tests proving the catalogue entry and global command dispatch exist. Workflow
   tests must cover ambiguity, unauthorized use, cancellation, and idempotent/repeated scans where
   applicable.
9. Kiosk/full-screen acceptance using only the scanner. Routine acceptance must not rely on mouse,
   touchscreen, physical keyboard, browser address bar, or Desk form access.

## Input conventions

- `CFG:CMD:*` performs an operational command.
- `CFG:SELECT:n` selects a numbered safe candidate only while an appropriate selection dialog is open.
- `CFG:QTY:GOOD:*`, `CFG:QTY:REJECT:*`, and `CFG:QTY:MATERIAL:*` provide contextual quantities.
  A Material value without `+` sets the armed quantity; a `+` value adds to it and may be scanned
  repeatedly before the related physical material identity.
- `CFG:CMD:CONFIRM`, `CFG:CMD:CANCEL`, and `CFG:CMD:DISMISS` provide consistent completion and escape
  paths.
- Physical Card, Employee, Handling Unit, Stock Tag, WIP Bin, Station, and location labels identify
  real entities. They are printed from their owning records and are not command labels.

## Safety rules

- A command must never select an ambiguous record merely because it is first in a list.
- Scanner actions reuse the same permission, state, quantity, ERPNext, and audit checks as touch actions.
- Confirmation scans must not bypass Supervisor approvals, reason requirements, or ERPNext submission
  prerequisites.
- Controlled reversal and correction may retain a supervised reason-entry step. The routine workflow
  and safe cancel/exit path must remain scanner-accessible.
- Background refresh must never replace a scanner dialog, consume its scan, move focus to the page
  scanner, or change the active Card while an operator action is in progress.

## Definition of done

A Production Kanban change is scanner-complete only when the operator can start from **Scanner Ready**,
open the action, resolve all choices, enter applicable quantities, scan physical identities, confirm or
cancel, recover from an error, and return to **Scanner Ready** without touching the screen.
