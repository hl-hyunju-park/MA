# v0.2 비전-QA 평가 — wiki agent (dataset=v0.2)

**전체: 54문항 · 평균 0.69**

### 프로젝트(doc)별

| 그룹 | n | mean |
|---|---|---|
| CAESAR | 14 | 0.46 |
| LIFE | 12 | 0.83 |
| STELLA | 28 | 0.75 |

### 능력축(capability)별

| 그룹 | n | mean |
|---|---|---|
| C1-binding | 10 | 0.85 |
| C2-visualonly | 8 | 0.75 |
| C3-structural | 25 | 0.66 |
| C4-reconcile | 7 | 0.64 |
| C5-honesty | 4 | 0.50 |

### 시각유형(visual_type)별

| 그룹 | n | mean |
|---|---|---|
| data_chart | 13 | 0.58 |
| dense_multipanel | 5 | 0.60 |
| heatmap_matrix | 6 | 0.83 |
| structure_diagram | 11 | 0.77 |
| table_image | 19 | 0.71 |

### 난이도(difficulty)별

| 그룹 | n | mean |
|---|---|---|
| 3 | 33 | 0.80 |
| 4 | 21 | 0.52 |

## 문항별

| ID | doc | capability | score | verdict | reason |
|---|---|---|---|---|---|
| S01 | STELLA | C3-structural | 1.0 | correct | 골든 정답에서 요구하는 '센트로이드 제1호 차이나 PEF'와 '4.13%'를 정확하게 포함하여 답변하였습니다. |
| S02 | STELLA | C3-structural | 1.0 | correct | 모-자 관계(센트로이드 인베스트먼트 파트너스 → 센트로이드 매니지먼트)와 내부거래 항목 및 금액 3종이 골든 정답과 모두 일치합니다. |
| S03 | STELLA | C3-structural | 1.0 | correct | 자금 흐름 순서, SPC 지분율(100%), 인수 금액(540억원) 및 인수 방식(구주+신주)을 모두 정확하게 명시하였습니다. |
| S04 | STELLA | C3-structural | 1.0 | correct | DCF가 시장가치 접근법보다 높다는 방향성과 구체적인 수치를 정확하게 제시하였습니다. |
| S05 | STELLA | C1-binding | 0.5 | partial | 모든 연도에서 Management Case가 더 크다는 점과 차이 금액은 정확히 제시하였으나, 최대 차이 연도로 FY28과 FY29가 동률임을 명시하지 않고 FY28 하나만 답하였으므로 rubric에 따라 부분 인정함. |
| S06 | STELLA | C2-visualonly | 0.0 | incorrect | 골든 정답에 명시된 구체적인 수치(-106,567백만원)를 제시하지 못하고 확인 불가하다고 답변함. |
| S07 | STELLA | C3-structural | 0.5 | partial | 최대 발산 연도(2022년)와 수치는 정확히 맞혔으나, 최소 수렴 연도를 2023년이 아닌 2021년으로 잘못 판정하였습니다. |
| S08 | STELLA | C3-structural | 1.0 | correct | 펀드명(센트로이드제2호바이아웃), 설정 연도(2017년), 만기 연도(2026년), 존속기간(9년)을 모두 정확하게 답변하였습니다. |
| S09 | STELLA | C3-structural | 1.0 | correct | 루브릭에서 요구한 음수 펀드 2개(제1호 차이나, 제3호 그로쓰창업벤처전문)와 각각의 수치((2.7)%, (54.4)%)를 정확하게 모두 식별하였습니다. |
| S10 | STELLA | C1-binding | 1.0 | correct | MGT 전 기간 우위, FY28 최대 격차(FY28~29 동률 구간 내 포함), FY28의 MGT(59,137) 및 DTT(22,398) 수치를 모두 정확하게 답변하였습니다. |
| S12 | STELLA | C4-reconcile | 1.0 | correct | 에이전트가 FY23 영업비용 7,278백만원을 정확히 읽었으며, 골든값 7,277.7백만원과 반올림 차이로 일치한다고 올바르게 판정하였습니다. |
| S14 | STELLA | C2-visualonly | 1.0 | correct | 최대 출자자인 새마을금고와 금액 5,900억원을 정확히 명시하였으며, 녹색 강조 출자자 두 곳을 모두 올바르게 답변하였습니다. |
| S15 | STELLA | C4-reconcile | 0.5 | partial | PDF와 엑셀의 수치 및 차이 금액은 정확히 계산하였으나, 차이의 원인(배당금수익 분류 차이)을 설명하지 못하고 확인 불가라고 답함. |
| S16 | STELLA | C4-reconcile | 1.0 | correct | 매도가능증권 Dec-23 잔액 12,296을 정확히 읽었으며, BS 엑셀 값과 일치함을 올바르게 확인하였습니다. |
| S17 | STELLA | C3-structural | 1.0 | correct | 방법(GPC)과 최저값(2,244), 최고값(132,347)을 모두 정확하게 맞혔습니다. |
| S18 | STELLA | C4-reconcile | 0.5 | partial | 잔액과 조정액 수치는 정확히 읽었으나, BS 엑셀 값(9,374.72)과의 일치 여부를 '일치하지 않는다'고 잘못 판정함. |
| S19 | STELLA | C1-binding | 1.0 | correct | 에이전트가 골든 정답과 일치하는 지분가치 85,605백만원을 정확하게 제시하였습니다. |
| S20 | STELLA | C3-structural | 1.0 | correct | 방향(감소)과 양 끝값(95,841, 77,659)을 모두 정확하게 답변하였습니다. |
| S21 | STELLA | C2-visualonly | 1.0 | correct | 조합(WACC 13.5%, PGR 2.0%)과 값(100,006백만원)을 모두 정확하게 맞혔습니다. |
| S22 | STELLA | C1-binding | 1.0 | correct | 회사명(Q Capital Partners)과 값(2.4x)을 모두 정확하게 답변하였습니다. |
| S23 | STELLA | C3-structural | 0.0 | incorrect | 에이전트가 제외된 회사(SV Investment)를 찾지 못했고, 데이터에 명시되어 있지 않다고 잘못 답변함. |
| S24 | STELLA | C3-structural | 1.0 | correct | 골든 정답에서 요구한 마이너스 배수 거래 3건(Plutus 1건, Neoplux 2건)을 정확하게 모두 식별하였습니다. |
| S25 | STELLA | C5-honesty | 0.0 | incorrect | 표에 대상회사 자체 배수가 없음을 명시해야 함에도 불구하고, 상장사 통계치인 중앙값(13.0x) 등을 대상회사의 배수로 단정하여 답변함. |
| S26 | STELLA | C5-honesty | 0.0 | incorrect | 표에 존재하지 않는 PGR 2.5%에 대해 임의의 수치를 제시하여 환각을 일으켰습니다. |
| S27 | STELLA | C1-binding | 1.0 | correct | 대표이사 직속 부문 수(5개)와 인원이 가장 많은 부문(투자본부 10명)을 모두 정확하게 답변하였습니다. |
| S28 | STELLA | C2-visualonly | 1.0 | correct | 회사명, 공시일, Deal Value 수치를 모두 정확하게 답변하였습니다. |
| S29 | STELLA | C4-reconcile | 1.0 | correct | 총원 25명 일치 및 부문별 인원 매핑(부동산투자자문=부동산, 준법감시팀=법무, 경영관리본부=관리본부)을 정확하게 확인하였습니다. |
| S30 | STELLA | C4-reconcile | 0.0 | incorrect | 본문의 '13개'라는 오기를 그대로 수용하였으며, 실제 펀드 개수를 14개가 아닌 8개로 잘못 파악하여 불일치 원인을 오답으로 설명함. |
| L01 | LIFE | C2-visualonly | 0.0 | incorrect | 교차 연도를 2022년이 아닌 2021년으로 잘못 답변하였으며, 수치 또한 대상사와 업계 평균을 반대로 읽었습니다. |
| L02 | LIFE | C2-visualonly | 1.0 | correct | 가장 큰 감소 요인인 'CSM 조정(-2,854억원)'과 추가 감소 요인인 'CSM 상각(-688억원)'을 모두 정확하게 답변하였습니다. |
| L03 | LIFE | C1-binding | 1.0 | correct | 상품군(생존보험(연금형)), 2023년 값(0.4), 2025년 값(4.2), 증가폭(3.8)을 모두 정확하게 제시하였습니다. |
| L04 | LIFE | C2-visualonly | 1.0 | correct | 가장 큰 비중 종목(사망), 비중(66.2%), CAGR(1.14%)을 모두 정확하게 제시하였습니다. |
| L05 | LIFE | C3-structural | 1.0 | correct | 보장성 13위, 저축성 11위 순위를 정확히 매칭하였으며, 두 부문 모두 수입보험료가 업계 평균보다 아래임을 정확하게 답변하였습니다. |
| L06 | LIFE | C3-structural | 1.0 | correct | 팀 수 5개와 5개 팀명을 골든 정답과 정확히 일치하게 답변하였습니다. |
| L07 | LIFE | C2-visualonly | 1.0 | correct | 연월(2018.9), PBR(1.08배), 인수자(금융지주A=신한금융) 및 대상사를 모두 정확하게 식별하였습니다. |
| L08 | LIFE | C4-reconcile | 0.5 | partial | 저축성보험료 증가와 영업이익률 하락 및 상충 관계는 정확히 짚었으나, FY23 영업이익률 수치를 9.81%가 아닌 2.98%로 잘못 기재하였습니다. |
| L09 | LIFE | C5-honesty | 1.0 | correct | 에이전트가 3개의 모형 박스(DB 추출, DB 배분, 최적 설계사 예측 모형)를 모두 정확히 명시하였으며, 적용 지점이 한 군데가 아니라고 올바르게 답변하였습니다. |
| L10 | LIFE | C1-binding | 1.0 | correct | 에이전트가 골든 정답과 일치하는 4,328억원을 정확하게 답변하였습니다. |
| L11 | LIFE | C3-structural | 0.5 | partial | 세 가지 수치는 정확하게 제시하였으나, rubric에서 요구한 추세(급감 후 횡보)에 대한 설명이 누락되었습니다. |
| L12 | LIFE | C1-binding | 1.0 | correct | 담보유형(기타대출)과 비중(37.5%)을 모두 정확하게 답변하였습니다. |
| CS-01 | CAESAR | C3-structural | 0.5 | partial | 신설 예정 법인 및 펀드 목록은 정확히 식별하였으나, 테두리 스타일(실선/점선)의 구분과 그 의미를 판별할 수 없다는 정직성(C5) 요건을 충족하지 못함. |
| CS-02 | CAESAR | C3-structural | 0.0 | incorrect | 골든 정답에서 명시한 하늘색 박스 법인 5개를 전혀 언급하지 않았으며, 엉뚱한 법인들을 답변하였습니다. |
| CS-03 | CAESAR | C3-structural | 0.0 | incorrect | 최상단 지주 법인을 명확히 확정하지 못하고 상충한다고 답했으며, 보유율 또한 질문에서 요구한 '최상단 지주가 핵심 지주를 보유하는 비율'이 아닌 '핵심 지주가 그 하위 법인을 보유하는 비율'을 답함. |
| CF-01 | CAESAR | C3-structural | 0.5 | partial | 경영진 가치는 정확히 답변하였으나, 자문사 가치에서 Base Case만 언급하고 Worst와 Best 케이스를 누락하여 rubric 기준에 따라 부분 점수를 부여함. |
| CF-02 | CAESAR | C3-structural | 0.0 | incorrect | 에이전트는 DCF와 시장접근법의 수치를 서로 다른 통화(USD vs KRW)로 잘못 인식하여 단순 비교함으로써 '시장접근법이 더 낮다'고 단정했으며, 이는 시나리오별로 결과가 달라진다는 골든 정답 및 rubric의 핵심 내용과 배치됩니다. |
| CK-01 | CAESAR | C3-structural | 0.0 | incorrect | 경영진안이 자문사안보다 크다고 해야 하는데, 반대로 자문사안이 더 크다고 답변하여 방향이 완전히 틀렸습니다. |
| CK-02 | CAESAR | C3-structural | 0.0 | incorrect | 자문사가 경영진보다 1년 지연(이연)시켰다는 골든 정답과 달리, 자문사가 더 이른 시점에 출시한다고 반대로 답변함. |
| CP-01 | CAESAR | C3-structural | 1.0 | correct | 에이전트가 골든 정답과 일치하는 Aidi와 MOIC 9.2x를 정확하게 답변하였습니다. |
| CP-02 | CAESAR | C1-binding | 1.0 | correct | 완전 엑싯 1건(Atium 외부 LP)과 부분 회수 3건(Atium, Catalyte, Union pay)을 정확히 구분하여 답변하였습니다. |
| CP-03 | CAESAR | C3-structural | 1.0 | correct | FY24 데이터 기준으로 자체 펀드 4.7m(약 81%), 외부 LP 1.1m(약 19%) 및 명칭 구분까지 골든 정답과 일치함. |
| CT-01 | CAESAR | C3-structural | 0.5 | partial | 경영진 전망이 더 높다는 방향성은 정확히 맞췄으나, rubric에서 요구한 '자문사의 85% 달성률 적용 하향 추정'에 대한 설명이 누락되었습니다. |
| CE-01 | CAESAR | C3-structural | 1.0 | correct | 자체 펀드 Manager Fee가 계약 2.0%를 상회하며 2.3% → 2.8% → 2.4%로 움직였다는 핵심 내용을 정확히 짚었습니다. |
| CE-02 | CAESAR | C1-binding | 0.0 | incorrect | 지급 대상 SPV 수를 12개가 아닌 30개로 잘못 답변하여 골든 정답 및 채점 기준과 일치하지 않습니다. |
| CH-01 | CAESAR | C5-honesty | 1.0 | correct | 개별 회사별 베타 값은 확인되지 않으며 평균 베타 값만 존재한다는 점을 정확히 답변하였습니다. |
