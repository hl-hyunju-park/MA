# Project Stella — Workbook Analysis (per-sheet, M&A view)

Valuation model for **Centroid Investment Partners** (센트로이드인베스트먼트파트너스(유) — the
licensed asset-manager / GP opco) and **Centroid Management** (legal vehicle **JHJ Invest Co.**
/ 제이에이치제이인베스트 — a levered investment-holding shell). 63 sheets, valuation date
**31-Dec-2024**, forecast **FY25–FY29 + terminal**. Units: mostly **KRWm** (₩m); `AUM Projection`
and `IRR` use 억원 / KRWmn.

---

## 0. The sheet-naming scheme *is* the schema

Sheet names are not labels — they encode the graph's node typing. Decoding the convention
gives section · entity · fund · metric · case for free:

| Token in name | Meaning | Example |
|---|---|---|
| `… >>` | **divider tab** → top-level Section | ` Biz Plan>>`, `Fin.Model>>`, `BSPL>>`, `PPT >>` |
| `>>4.1…` / `>>4.2…` | **entity** sub-divider inside BSPL | 4.1 = Investment Partners, 4.2 = Management |
| `장표 #N` | **exhibit** (PPT presentation sheet), numbered | `DCF 장표 #1`, `Revenue 장표 #3` |
| `_MGT` / `_DTT` | **valuation case**: Management vs Deloitte | `DCF 장표 #1_MGT`, `#2_DTT` |
| `<fund>_비용` | fund **costs** | `제2호_비용` |
| `<fund>_거래내역` | fund **bank transaction ledger** (raw) | `7호&7-1호_거래내역` |
| `<fund>_관리보수` | fund **management-fee schedule** | `차이나1호_관리보수` |
| `제N호` + word | **fund vintage N** + strategy | 제2호**바이아웃**=Buyout, 제3호**그로쓰**=Growth, 제8호**코인베스트**=Co-invest |
| fund proper noun | region/deal | `차이나`=China, `옐로씨`=Yellow Sea |
| `4.1X` / `4.2X` | entity-prefixed **statement** | `4.1BS`, `4.2PL` |
| `_` underscore variant | **raw filed statement (₩)** vs summary roll-up (₩m) | `4.2_BS` (raw) vs `4.2BS` (summary) |
| `(A)` | **Actual** | `PL_FY24(A)` |
| `EIU(KR)` / `EIU(US)` | macro source, by country | Economist Intelligence Unit |

This maps 1:1 onto the target property graph: divider→`Section`, `4.x`→`Entity`,
`제N호…`→`Fund`, `_비용/_관리보수/성과보수`→`Metric`, `_MGT/_DTT`→case attribute,
`장표 #N`→exhibit node. The cell→Metric pass can seed labels straight from these tokens.

---

## 1. PPT >> — downstream exhibits (numbers come from Fin.Model, never source-of-truth)

- **Football Chart** — valuation "football field". Equity value by method: DCF-MGT ≈ **168–207 ₩bn**,
  DCF-DTT ≈ **38–40 ₩bn** (`G5=DCF!K59`), Market (GPC/GTC) **24–132 ₩bn** (EBITDA 4,212 × 7.6–33× multiples,
  +net cash 7,703).
- **Bridge** — waterfall MGT→DTT: **MGT 210,835 → AUM adj −18,664 → Exit-value adj −106,567 → DTT 85,605**.
  The ~125 ₩bn case gap is **exit value + AUM**, *not* discount rate. Exit-value sensitivity ±20% ⇒ equity
  ±~28 ₩bn (MGT) / ±~17 ₩bn (DTT).
- **DCF 장표 #1_MGT** — management-case DCF exhibit. Equity **206,131**; WACC 16%, PGR 1%; value concentrated in
  **FY26** (revenue spikes to 468,818 on performance fees).
- **DCF 장표 #2_DTT** — Deloitte-case DCF exhibit, a live mirror of `DCF` (`E12=DCF!K59`). Equity **39,128**; EV
  45,637; robust to WACC/PGR (38–40 ₩bn) ⇒ gap is operating-assumption-driven.
- **Revenue 장표 #1** — operating-revenue composition both cases. Lines: 관리보수 mgmt fee · 성과보수 perf fee ·
  배당금수익 dividends · 자문용역수수료 advisory. FY26 total: MGT 468,818 / DTT 166,999 — the spike is 성과보수.
- **Revenue 장표 #2** — mgmt fee **by fund**; legacy funds (2/3/5/7) run off, recurring revenue depends on the
  assumed **신규펀드 (new fund)** raise (MGT ramps to 53,699 by FY29 vs DTT 8,705).
- **Revenue 장표 #3** — perf fee **by fund** (DTT): essentially **only Fund 7 in FY26 = 135,635**. The entire
  upside is one realization event.
- **Revenue 장표 #4** — dividend income by fund (DTT): small/lumpy, mostly FY26 (Fund 7 = 23,940).
- **Operating expenses 장표 #1–3** — total OpEx, then 인건비 personnel detail, then 기타경비 other-expense ledger.
  Labor-dominated; D&A <1%. **FY26 personnel/bonus spike** (sourced from `Operating Expense` T-column) is a
  carry-linked accrual to normalize.
- **GP Commitment 장표** — GP co-investment cash calls (negative = outflow). MGT far heavier on forward
  commitments (FY28 −36,734 vs DTT −12,771) — tied to assumed new-fund launches.
- **NWC 장표** — net working capital; **negative throughout** (선수수익 prepaid mgmt fees > 매출채권 AR) ⇒
  self-funding, cash-favorable.
- **CapEx 장표** — capex ~10 ₩m/yr forward ⇒ **asset-light**, EBITDA ≈ FCF before WC.

## 2. Fin.Model >> — the valuation engine

- **Cover** — control sheet: KRW, val date 31-Dec-2024, FYE Dec, model end 31-Dec-2029.
- **DCF** — headline. FCFF = EBITDA + ΔNWC − CapEx − GP commit − Tax, discounted at WACC.
  **Case switch `DCF!J6` currently = 2 (DTT).** Summary: PV proj **44,472** + PV terminal **230** =
  Operating value 44,702; + NOA 935 = **EV 45,637**; + net debt −6,509 = **Equity 39,128 (K59)**.
  Terminal value immaterial ⇒ value = explicit cash flows, dominated by **FY26 carry (135,635 rev → 20,000 tax)**.
  Cap table: 정진혁 65% / 신창호 35% / 박복자 ~0% of 150,000 shares.
- **Operating Revenue** — 관리보수 + 성과보수 + 배당금 + 자문용역수수료, broken out by fund. Recurring fee annuity
  ~9–12 ₩bn/yr + lumpy carry in FY26/27.
- **Operating Expense** — 인건비 + 기타비용 + D&A; people-heavy; FY26 spike is event-linked.
- **GP Commitment** — GP's own fund commitments (기존펀드 + 신규펀드); −12,771 FY28 is the big outflow.
- **CapEx & DA** — capex/D&A both immaterial (<₩15m/yr); confirms asset-light.
- **NWC** — ΔNWC small, revenue-linked; forecast days frozen at FY24 (~39 DSO).
- **Net debt, NOA** — the EV→equity bridge. **Net debt −6,508.5** (cash 159 − ST debt 480 − current LT debt 5,000 −
  severance 1,188) → `DCF!K58`; **NOA +934.7** (loans 87.5 + suspense 705 + memberships 142) → `DCF!K56`.
- **Tax** — Korean progressive schedule incl. 10% local surtax (11% / 22% / 24.2% / 27.5% bands). FY26 tax ≈ 20,000.

## 3. Fin.Model >> — revenue drivers & macro

- **AUM Projection** — master driver: cumulative AUM **29,000 → 69,000 억원 (2024→2028E)**, ~2.4×, from *new fund
  formation* (project deals + blind funds). Built bottom-up (Loan = EV×#Deals×LTV, etc.); 회사제시 vs DTT toggle =
  `DCF!M6`.
- **관리수수료 (management fees)** — per-fund realized fee **rates 0.4–2.0%** (blended ~1% on committed capital);
  biggest = 제7호 619.2 ₩bn @1.0% = 6,192 ₩m/yr. This is the **rate source**; AUM Projection is the base.
- **성과보수, 배당금 (perf fee / carry & dividends)** — carry terms uniform **8% hurdle / 20% carry**; material only
  for **제7호 (135,635)** and **제8호 (20,048)**, exits 2026–28. MGT/DTT toggle = `DCF!J6`.
- **임직원 수 / 인력 (headcount)** — **4 → 25 employees (2020→2024)**, investment team largest/most senior
  ⇒ key-person risk; drives personnel OpEx.
- **고정자산명세서 (fixed-asset register)** — office equipment + leasehold fit-out only ⇒ asset-light.
- **EIU(KR) / EIU(US)** — macro anchors: KR lending rate 4.9→3.2%, real GDP ~2.5%, FX ~1,250 ⇒ supports
  WACC/terminal-growth inputs.

## 4. Biz Plan >> — per-fund detail (upstream inputs/actuals; leaf nodes, no live link up to Fin.Model)

**IRR** — *forward* return model for a planned **₩500 ₩bn blind fund** (+ ₩2.5tn project/co-invest fund):
**Gross IRR 20.98% / Net IRR 19.11%**, 1.5–2% mgmt + 20% carry over 8% hurdle, plus a stated **₩1tn follow-on by
2028**. This is the growth story underpinning AUM Projection.

Historical funds (name = vintage + strategy + deal):

| Fund (name decode) | AUM | Fee rate | GP fee/yr | Underlying deal | Status |
|---|---|---|---|---|---|
| 차이나1호 (China No.1) | 7.5 ₩bn | 2%→1% | runoff | China buyout (USD) | wind-down; **unpaid/accrued fees** from 2018 |
| 제2호 바이아웃 (No.2 Buyout) | 44.5 ₩bn | 2.0% | ~890 ₩m | leveraged buyout (SPC + ₩5bn debt) | fees → 0 by 2023 |
| 제3호 그로쓰 (No.3 Growth) | 5.8 ₩bn | ~0.4% | minimal | CB / growth deal (씨엔아이) | distributed to LPs 2021–22 |
| 옐로씨 (Yellow Sea No.1) | 55.0 ₩bn | 1.5% | 825 ₩m | Kolon Fiber buyout | mature, stable |
| 제5호 바이아웃 (No.5) | 120.9 ₩bn | 1.5% | 1,813 ₩m | Prestige Property (real estate) | **distributing dividends** |
| 제7호 바이아웃 (No.7) | 619.2 ₩bn | 1.0% | 6,192 ₩m | **TaylorMade Golf** (flagship) | live; co. pays mgmt fee back to fund |
| 제7-1호 (No.7-1, parallel) | 471.5 ₩bn | 0.5% | 2,358 ₩m | TaylorMade (co-invest) | live |
| 제8호 코인베스트 (No.8) | 72.4 ₩bn | 1.5% | 1,086 ₩m | TaylorMade co-invest (golf club mgmt) | live; `#REF!` cells to fix |

Suffix decode per fund: `_비용` = annual cost/fee table (top row = GP fee = AUM×rate); `_거래내역` = raw bank
ledger (capital calls, deal payments, distributions — the audit trail); `_관리보수` = quarterly fee accrual
schedule (only China-1 & Fund-2 have a separate one; others embed it in `_비용`).

## 5. BSPL >> — financial statements (historical actuals; latest = 1H FY24, plus FY24(A))

**Entity 4.1 — Centroid Investment Partners** (`BS`/`PL`/`4.1BS`/`4.1PL`):
the profitable fee opco. FY23 revenue 13,012, EBIT 5,734 (~44% margin), NI 5,065. **FY24 actual (`PL_FY24(A)`)
is a −1,725 loss** from a 2,413 bad-debt write-off + 1,026 AFS impairment (both ~non-recurring — normalize).
Dec-24 equity +7,611; net debt ≈ +5.3 ₩bn.

**Entity 4.2 — Centroid Management / JHJ Invest** (`4.2BS`/`4.2PL`/`4.2_BS`/`4.2_PL`):
a levered holding shell — ~0 operating revenue, ~6.9 ₩bn AFS securities funded by ~10.5 ₩bn long-term debt,
chronic losses (interest), **negative equity −5.2 ₩bn**. Treat separately; look through to the portfolio.

The `_` variants (`4.2_BS` vs `4.2BS`) are **raw filed statement (₩) vs KRWm summary roll-up**
(`summary = SUMIFS(raw, code)/1e6`), not actuals-vs-restated — both are actuals.

---

## Bottom line for an acquirer

1. **Two values:** defensible **DTT equity ≈ ₩39 ₩bn** (EV ₩46 ₩bn) vs management stretch **MGT ≈ ₩206 ₩bn**.
   The ~₩125 ₩bn gap is **exit value (~₩107 ₩bn) + new-fund AUM (~₩19 ₩bn)**, not the discount rate.
2. **Single-event concentration:** value hinges on the **FY2026 Fund-7 (TaylorMade) exit carry** (₩135.6 ₩bn rev).
   Stress that one assumption above WACC/PGR.
3. **Quality:** recurring mgmt-fee annuity (~₩9–13 ₩bn/yr, ~40% margins), asset-light, self-funding (negative) NWC,
   live crown-jewel (TaylorMade) paying fees back. Track record: Funds 3 & 5 already distributing.
4. **Diligence flags:** FY24 one-off losses (bad debt + AFS impairment); China-1 unpaid/accrued fees; Fund-8 `#REF!`
   cells; Centroid Management negative equity / debt look-through; realism of the new-fund (신규펀드) raise behind
   the IRR sheet's 21%/19% target.
