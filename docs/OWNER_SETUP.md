# The owner's setup as described by the owner (requirements for the engine)

Source: owner's messages and a worked example. This is the reference that the detectors, exits and
analysis must eventually reproduce. Items marked TODO are not in the engine yet.

## Timeframe mapping (entry timeframe follows the zone timeframe)

| zone | entry on | target on |
|---|---|---|
| H1 FVG / H1 fractal | M1 (M1 to M3 patterns) | H1 levels |
| H4 zone | M5 | H4 levels |
| M15 zone | M1, until the M15 zone is reached | M15 levels |

Implemented: H1 zones with M1 and M3 patterns. TODO: M15 and H4 zone books and the entry timeframe
that goes with each (an `entry_tf` per zone timeframe).

## Targets are structural, not fixed R

The target sits on the zone's own timeframe: the next unswept fractal in the trade direction, or the
fill of an opposing FVG (often half of it), whichever comes first; a fractal on the way to an FVG is
a valid target. The result in R is therefore variable (stop distance against distance to the level),
and large (10R to 20R) because the stop is a few bps. The owner usually closes at 5R or lower in
practice but wants targets of 3R, 5R, 10R, 15R and more tested.

Implemented: fixed-R first-passage ladder (1R to 15R). TODO: first passage of structural levels
(nearest H1 fractal in the direction, FVG edge, FVG midpoint), stored with their distance in R.

## Setup pattern

Stall, then a sideways range inside the zone where a reaction is possible, with re-sweeps. The stop is
as local as possible on M1 (beyond the M1 extreme).

## Re-entries (campaign)

After a stop-out the owner re-enters with small size until the move is caught or the daily loss limit
is reached. The unit of analysis is therefore a campaign per zone episode: attempts one after another
(the next only after the previous closed), stop after the first target hit, a cap on attempts, and a
daily loss limit. Each attempt pays its own costs.

TODO: derive campaigns offline from the per-candidate data (entry time, exit time, outcome under a
chosen exit policy), with the attempt cap and the daily limit as parameters.

## Worked example, 2025-10-27, SOLUSDT (Upscale demo, long)

An H1 zone with a large rejection wick; an H1 fractal that is tested again; entry on M1 near the
swept low after a stall. Entry about 198.52, stop 198.40 (about 6 bps), take profit 201.00 (about 125
bps, about 20R). Price reached the H1 target area within about two hours (a spike to 202.11).
The setup is: price arrives at the H1 zone, stalls, goes sideways in the zone, sweeps, and the M1
micro-stop is placed beyond the local extreme. The two screenshots (M1 with the trade, and the H1
context with zones) are with the owner.
