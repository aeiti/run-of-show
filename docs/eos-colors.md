# Eos colours

The colour rules the board should follow when it shows Eos-style information. [eos-mockup.html](eos-mockup.html) is the visual target: open it in a browser and use its Live/Blind toggle.

None of this is in the app yet. `frontend/src/index.css` has its own palette; [Mapping to the app](#mapping-to-the-app) says how the two line up.

## Base

| Token | Hex | Use |
|---|---|---|
| `--eos-bg` | `#0A0A0A` | Display background |
| `--eos-row` | `#141414` | Row and tile background |
| `--eos-grid` | `#2A2A2A` | Grid lines, header rule |
| `--eos-text` | `#CFCFCF` | Default text |

## Value colours

A channel's level is coloured by **where the value comes from** and **how it changed**. A solid colour means the value has arrived; a lighter tint of the same hue means it is still moving.

| Meaning | Arrived | Moving |
|---|---|---|
| Manual, unstored | `--eos-manual` `#FF2A2A` | `--eos-manual-moving` `#FF7A7A` |
| Manual from another user | `--eos-manual-other` `#9E1B1B` | — |
| Intensity up from the previous cue | `--eos-up` `#3C9DE0` | `--eos-up-moving` `#8FC8EE` |
| Intensity down from the previous cue | `--eos-down` `#38B438` | `--eos-down-moving` `#88D888` |
| Tracked (unchanged) | `--eos-tracked` `#C840C8` | `--eos-tracked-moving` `#E090E0` |
| Blocked | `--eos-blocked` `#FFFFFF` | — |
| Unowned / null | `--eos-unowned` `#8A8A8A` | — |
| From a submaster | `--eos-sub` `#E8E030` | — |
| Staging mode | `--eos-staging` `#E6B422` | — |
| Temp fader (palette) | `--eos-tempfader` `#9A6530` | — |
| Augment3d override | `--eos-augment3d` `#FF86C4` | — |

Reference letters under a level (`B`, `n`, `P`, `C`, a palette like `CP5`) take the colour of what they refer to, not the level's colour. In the mockup `CP5` is tracked magenta under a blue level.

## Channel numbers

The channel number shows the channel's state, separately from its level.

| State | Token | Hex | Notes |
|---|---|---|---|
| Normal | `--eos-chan-normal` | `#D8D8D8` | |
| Unpatched | `--eos-chan-unpatched` | `#8A8A8A` | Level shows `—` |
| Parked | `--eos-chan-parked` | `#FFFFFF` | Bold number |
| Captured | `--eos-chan-captured` | `#E6B422` | |

A selected channel gets a 1px outline: gold in Live, `--selected-outline` blue in Blind.

## Live and Blind

The chrome (current row, selection, command line) is **gold in Live** and **blue in Blind**. Blind also gives the whole display frame a blue border and an inner glow, so you can't mistake which mode you're editing in.

| Token | Live | Blind |
|---|---|---|
| `--current-fill` | `#E0A800` | `#2F6FB0` |
| `--current-bg` | `#3A2E0C` | `#0F2742` |
| `--current-text` | `#FFC72C` | `#7FB4E8` |
| `--selected-outline` | `#E6B422` | `#3A7BD5` |
| `--cmdline` | `#E6B422` | `#5AA0E0` |
| `--frame-border` | transparent | `#2F6FB0` |

The command line is prefixed `LIVE` or `BLIND`.

## Playback status display (cue list)

- **Current cue:** filled. Background `--current-bg`, text `--current-text`, a 3px `--current-fill` bar at the left edge, and a bold cue number.
- **Selected cue:** a 1px `--selected-outline` outline, no fill. Current and selected are different things and can be different rows.
- **Fade in progress:** the cue's Up time counts down in `--psd-fade` `#D0342C`, bold, in brackets (`[2.4]`). **Live only**: Blind never shows it.
- **Follow / hang:** the countdown (`follow 0:05 ↓`) and the go marker `>` are `--psd-followhang` `#38B438`.
- **Flags** (`M`, `L`, `B`, `>F5`): muted grey `#9A9A9A`.

## Fader ribbon

Each fader's value is coloured by what is on it.

| Source | Token | Hex |
|---|---|---|
| Grand master, inhibitive sub | `--fader-gm` | `#D0342C` |
| Additive sub | `--fader-sub` | `#E8E030` |
| Playback fader | `--fader-pb` | `#38B438` |
| Preset / palette | `--fader-preset` | `#E8912A` |

## Mapping to the app

The app's palette (`frontend/src/index.css`, as of October 2026) against the Eos roles:

| App token | Hex | Closest Eos role | Notes |
|---|---|---|---|
| `--bg` | `#0a0b0d` | `--eos-bg` | Near match |
| `--panel` | `#111318` | `--eos-row` | Near match |
| `--line` | `#22262d` | `--eos-grid` | Near match |
| `--text` | `#d8dde4` | `--eos-text` | App is slightly brighter and cooler |
| `--go` | `#3ddc84` | `--psd-followhang`, `--fader-pb` | Used for the fade bar and GO, where Eos uses red for a fade in progress |
| `--stby` | `#d9a520` | `--current-fill` (Live) | Standby and the active cue, the role of Eos's gold chrome |
| `--err` | `#ff6b6b` | — | Errors; close to `--eos-manual-moving`, so avoid putting them side by side |

When adding Eos-style display to the app, add the `--eos-*` tokens to `:root` as they are needed, and don't repurpose `--go` or `--stby` for Eos meanings.
