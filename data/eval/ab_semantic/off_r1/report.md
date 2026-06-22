# v0.2 비전-QA 평가 — wiki agent (dataset=v0.2)

**전체: 54문항 · 평균 0.65**

### 프로젝트(doc)별

| 그룹 | n | mean |
|---|---|---|
| CAESAR | 14 | 0.39 |
| LIFE | 12 | 0.88 |
| STELLA | 28 | 0.68 |

### 능력축(capability)별

| 그룹 | n | mean |
|---|---|---|
| C1-binding | 10 | 0.75 |
| C2-visualonly | 8 | 0.88 |
| C3-structural | 25 | 0.52 |
| C4-reconcile | 7 | 0.64 |
| C5-honesty | 4 | 0.75 |

### 시각유형(visual_type)별

| 그룹 | n | mean |
|---|---|---|
| data_chart | 13 | 0.69 |
| dense_multipanel | 5 | 0.70 |
| heatmap_matrix | 6 | 1.00 |
| structure_diagram | 11 | 0.36 |
| table_image | 19 | 0.66 |

### 난이도(difficulty)별

| 그룹 | n | mean |
|---|---|---|
| 3 | 33 | 0.71 |
| 4 | 21 | 0.55 |

## 문항별

| ID | doc | capability | score | verdict | reason |
|---|---|---|---|---|---|
| S01 | STELLA | C3-structural | 1.0 | correct | 골든 정답에서 요구하는 '센트로이드 제1호 차이나 PEF'와 '4.13%'를 정확하게 포함하여 답변하였습니다. |
| S02 | STELLA | C3-structural | 0.0 | incorrect | 에이전트가 타임아웃 에러로 인해 답변을 제공하지 못했습니다. |
| S03 | STELLA | C3-structural | 1.0 | correct | 자금 흐름 경로, SPC 지분율(100%), 인수 금액(540억원) 및 인수 방식(구주+신주)을 모두 정확하게 명시하였습니다. |
| S04 | STELLA | C3-structural | 1.0 | correct | DCF가 시장가치 접근법보다 높다는 방향을 정확히 제시하였고, 구체적인 수치(85,605백만 원 및 419억 원)를 통해 그 차이를 명확히 설명하였습니다. |
| S05 | STELLA | C1-binding | 0.5 | partial | 모든 연도에서 Management Case가 더 크다는 점과 차이 금액은 정확히 제시하였으나, 최대 차이 연도로 FY28과 FY29가 동률임을 명시하지 않고 FY28 하나만 답하였으므로 rubric에 따라 부분 인정함. |
| S06 | STELLA | C2-visualonly | 0.0 | incorrect | 골든 정답인 -106,567백만원이 아닌 펀드별 다른 수치를 제시하였으므로 오답입니다. |
| S07 | STELLA | C3-structural | 0.5 | partial | 최대 발산 연도(2022년)와 수치는 정확히 맞혔으나, 최소 수렴 연도를 2023년이 아닌 2021년으로 잘못 판정하였습니다. |
| S08 | STELLA | C3-structural | 1.0 | correct | 펀드명(센트로이드제2호바이아웃), 설정 연도(2017년), 만기 연도(2026년), 존속기간(9년)을 모두 정확하게 답변하였습니다. |
| S09 | STELLA | C3-structural | 1.0 | correct | 루브릭에서 요구한 음수 펀드 2개(제1호 차이나, 제3호 그로쓰창업벤처전문)와 각각의 수치((2.7)%, (54.4)%)를 정확하게 모두 식별하였습니다. |
| S10 | STELLA | C1-binding | 0.5 | partial | MGT 전 기간 우위와 FY28 수치는 정확히 판독하였으나, 격차가 최대인 구간을 FY28~FY29가 아닌 FY29로만 단정하여 rubric에 따라 감점 처리함. |
| S12 | STELLA | C4-reconcile | 1.0 | correct | 에이전트가 FY23 영업비용 7,278백만원을 정확히 읽었으며, 골든값 7,277.7백만원과 반올림 차이로 일치한다고 올바르게 판정하였습니다. |
| S14 | STELLA | C2-visualonly | 1.0 | correct | 최대 출자자인 새마을금고와 금액 5,900억원을 정확히 명시하였고, 녹색 강조 출자자 두 곳을 모두 올바르게 답변하였습니다. |
| S15 | STELLA | C4-reconcile | 0.5 | partial | PDF와 엑셀의 수치 및 차이 금액은 정확히 계산하였으나, rubric에서 요구한 차이의 원인(배당금수익 분류 차이)을 설명하지 못하고 확인 불가라고 답함. |
| S16 | STELLA | C4-reconcile | 1.0 | correct | 매도가능증권 Dec-23 잔액 12,296을 정확히 읽었으며, BS 엑셀 값과 일치함을 올바르게 확인하였습니다. |
| S17 | STELLA | C3-structural | 1.0 | correct | 가장 폭이 넓은 방법(GPC)과 해당 방법의 최저값(2,244) 및 최고값(132,347)을 모두 정확하게 답변하였습니다. |
| S18 | STELLA | C4-reconcile | 0.5 | partial | 잔액(9,375)과 조정액((5,463))은 정확히 읽었으나, BS 엑셀 값과의 일치 여부를 '일치하지 않는다'고 잘못 판정함. |
| S19 | STELLA | C1-binding | 1.0 | correct | 에이전트가 골든 정답과 일치하는 지분가치 85,605백만원을 정확하게 제시하였습니다. |
| S20 | STELLA | C3-structural | 1.0 | correct | 방향(감소)과 양 끝값(95,841 및 77,659)을 모두 정확하게 답변하였습니다. |
| S21 | STELLA | C2-visualonly | 1.0 | correct | 조합(WACC 13.5%, PGR 2.0%)과 값(100,006)을 모두 정확하게 맞혔습니다. |
| S22 | STELLA | C1-binding | 1.0 | correct | 회사명(Q Capital Partners)과 수치(2.4x) 모두 골든 정답과 일치합니다. |
| S23 | STELLA | C3-structural | 0.0 | incorrect | 에이전트는 제외된 회사가 확인되지 않는다고 답했으나, 골든 정답과 rubric에서는 SV Investment가 수치 및 시각적 표식(음영/빗금)을 통해 제외되었음을 명시하고 있습니다. |
| S24 | STELLA | C3-structural | 1.0 | correct | 골든 정답에서 제시한 3건의 거래(Plutus 1건, Neoplux 2건)와 해당 수치를 정확하게 모두 식별하였습니다. |
| S25 | STELLA | C5-honesty | 0.0 | incorrect | 표에 대상회사 자체 배수가 없음을 명시해야 하나, 통계치인 중앙값 등을 대상회사의 배수로 단정하여 답변함. |
| S26 | STELLA | C5-honesty | 1.0 | correct | 제공된 데이터에서 해당 값을 확인할 수 없다고 정직하게 답변하여 채점 기준을 충족함. |
| S27 | STELLA | C1-binding | 0.0 | incorrect | 대표이사 직속 부문 수(5개)와 최다 인원 부문(투자본부 10명) 모두 골든 정답과 일치하지 않습니다. |
| S28 | STELLA | C2-visualonly | 1.0 | correct | 회사명, 공시일, Deal Value 수치를 모두 정확하게 답변하였습니다. |
| S29 | STELLA | C4-reconcile | 0.0 | incorrect | 골든 정답은 총원 및 부문별 인원이 모두 일치한다고 명시하고 있으나, 에이전트는 엑셀의 평균값을 사용하여 일치하지 않는다고 잘못 판정함. |
| S30 | STELLA | C4-reconcile | 0.5 | partial | 본문과 실제 데이터가 불일치한다는 점은 찾아냈으나, 실제 펀드 수가 14개라는 정확한 수치와 합산 오류(8+6=14)를 짚어내지 못했습니다. |
| L01 | LIFE | C2-visualonly | 1.0 | correct | 교차 연도(2022년)와 당시 대상사(83.9%) 및 업계(83.7%) 유지율 수치를 모두 정확하게 제시하였습니다. |
| L02 | LIFE | C2-visualonly | 1.0 | correct | 가장 큰 감소 요인인 'CSM 조정(-2,854억원)'과 추가 감소 요인인 'CSM 상각(-688억원)'을 모두 정확하게 답변하였습니다. |
| L03 | LIFE | C1-binding | 1.0 | correct | 상품군(생존보험(연금형)), 2023년 값(0.4), 2025년 값(4.2), 증가폭(3.8)을 모두 정확하게 제시하였습니다. |
| L04 | LIFE | C2-visualonly | 1.0 | correct | 최대 비중 종목(사망), 비중(66.2%), CAGR(1.14%)을 모두 정확하게 제시하였습니다. |
| L05 | LIFE | C3-structural | 1.0 | correct | 보장성 13위, 저축성 11위 순위를 정확히 매칭하였으며, 두 부문 모두 수입보험료가 업계 평균보다 아래임을 정확하게 답변하였습니다. |
| L06 | LIFE | C3-structural | 0.0 | incorrect | 팀 수를 1개로 잘못 답하였으며, 골든 정답에 명시된 5개 팀명을 모두 제시하지 못했습니다. |
| L07 | LIFE | C2-visualonly | 1.0 | correct | 연월(2018.9), PBR(1.08배), 인수자(금융지주A=신한금융) 및 대상사를 모두 정확하게 식별하였습니다. |
| L08 | LIFE | C4-reconcile | 1.0 | correct | 저축성보험료의 증가(1,266→1,377)와 영업이익률의 급락 및 적자 전환(9.81%→-6.7%)을 정확히 읽어내어 두 추세가 상충함을 명시하였습니다. |
| L09 | LIFE | C5-honesty | 1.0 | correct | 루브릭에서 요구한 3가지 모형 박스(DB 추출, 최적 설계사 예측, DB 배분 모형)를 모두 정확하게 명시하였습니다. |
| L10 | LIFE | C1-binding | 1.0 | correct | 에이전트가 골든 정답과 일치하는 4,328억원을 정확하게 답변하였습니다. |
| L11 | LIFE | C3-structural | 0.5 | partial | 세 가지 수치는 정확하게 제시하였으나, rubric에서 요구한 추세(급감 후 횡보)에 대한 설명이 누락되었습니다. |
| L12 | LIFE | C1-binding | 1.0 | correct | 담보유형(기타대출)과 비중(37.5%)을 모두 정확하게 답변하였습니다. |
| CS-01 | CAESAR | C3-structural | 0.0 | incorrect | 신설 예정 법인 중 New Fund III/IV 계열을 누락하였고, 테두리 스타일 구분 및 그 의미를 판별할 수 없다는 정직성(C5) 요건을 충족하지 못했으며, 근거 없는 신설 연도를 임의로 기재함. |
| CS-02 | CAESAR | C3-structural | 0.0 | incorrect | 골든 정답에서 명시한 하늘색 박스 법인 5개를 전혀 언급하지 않았으며, 엉뚱한 법인들을 답변하였습니다. |
| CS-03 | CAESAR | C3-structural | 0.0 | incorrect | 최상단 지주 법인을 Silver Treasure Inc.(Seychelles)가 아닌 CP Holdings I LLC로 잘못 답변하였습니다. |
| CF-01 | CAESAR | C3-structural | 1.0 | correct | 경영진 가정의 범위(282~360)와 자문사의 3가지 케이스(Worst 48, Base 111, Best 167) 수치를 모두 정확하게 제시하였습니다. |
| CF-02 | CAESAR | C3-structural | 0.5 | partial | 거래사례의 최저치(24)가 가장 낮다는 점은 정확히 짚었으나, 경영진 DCF가 가장 높고 자문사 DCF와 시장접근법이 겹친다는 핵심 맥락을 생략하고 시장접근법이 더 보수적이라고 단정적으로 결론지었습니다. |
| CK-01 | CAESAR | C3-structural | 0.0 | incorrect | 경영진안이 자문사안보다 크다는 골든 정답의 방향성과 달리, 대부분의 펀드에서 자문사안이 더 크다고 잘못 답변하였습니다. |
| CK-02 | CAESAR | C3-structural | 0.0 | incorrect | 자문사가 신규 펀드 결성을 1년 지연시켰다는 골든 정답과 달리, 시점 차이가 없다고 잘못 답변하였습니다. |
| CP-01 | CAESAR | C3-structural | 0.0 | incorrect | 채점 기준에 명시된 대로 Atium의 12.2x는 별도 지표이므로 오답이며, 포트폴리오 성과표상 최고치인 Aidi 9.2x를 정답으로 제시하지 않았습니다. |
| CP-02 | CAESAR | C1-binding | 1.0 | correct | 완전 엑싯 1건(Atium)과 부분 회수 3건(Atium, Catalyte, Union pay)을 정확히 구분하여 답변하였습니다. |
| CP-03 | CAESAR | C3-structural | 1.0 | correct | 골든 정답의 핵심 수치인 자체 펀드 4.7m(81%)와 외부 LP 1.1m(19%)를 정확히 제시하였으며, 명칭 구분까지 수행하였습니다. |
| CT-01 | CAESAR | C3-structural | 0.5 | partial | 경영진 전망이 더 높다는 방향성은 정확히 맞췄으나, rubric에서 정답 조건으로 명시한 '자문사의 85% 달성률 적용 하향 추정'에 대한 설명이 누락되었습니다. |
| CE-01 | CAESAR | C3-structural | 0.0 | incorrect | 에이전트가 자체 펀드 보수율(2.3%→2.8%→2.4%)을 짚지 못하고, 잘못된 계산을 통해 34%~45%라는 엉뚱한 수치를 제시하였습니다. |
| CE-02 | CAESAR | C1-binding | 0.5 | partial | 실제 지급 수(11개)는 맞게 답했으나, 지급 대상 수를 12개가 아닌 30개로 잘못 답하여 부분 점수를 부여함. |
| CH-01 | CAESAR | C5-honesty | 1.0 | correct | 개별 회사별 베타 값이 자료에 명시되어 있지 않음을 정확히 답변하였습니다. |
