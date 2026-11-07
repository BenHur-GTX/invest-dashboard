# 적립 대시보드

Ben의 미국 ETF 적립·폭락장 대응 대시보드. 정적 페이지(GitHub Pages) + GitHub Actions 데이터 갱신.

- `index.html` 화면과 판단 로직 (시장 상태 5단계, 월 적립 배분, QLD 3층, 실탄 4차, 거시 신호등, 과열 점수)
- `scripts/build_data.py` Yahoo·네이버·FRED·CNN 수집, 지표·백테스트 계산 → `data/market.json`, `data/backtest.json`
- `data/holdings.enc.json` 보유 내역 (공개 저장소이므로 암호화). 키는 각 기기 브라우저에만 저장
- `.github/workflows/update.yml` 평일 미국 장중 15분마다 갱신

규칙 근거: Band 전략 종합 분석 문서 (2026-11-07).
