# Kiwoom REST API Docs

- Generated at: 2026-07-03 13:51:53
- Source workbook: `키움 REST API 문서.xlsx`
- Scope: excludes domestic stock APIs; includes US stock APIs, OAuth, and error codes.
- Included sheets: 133 / 339
- Included API items: 132 / 338

## Links

- [API List](api-list.md)
- [API Categories](categories.md)
- [Included Sheets](#included-sheets)

## Major Category Summary

| Major Category | API Count |
| --- | --- |
| Common | 1 |
| OAuth 인증 | 2 |
| 미국주식 | 129 |

## Notes

- Domestic stock APIs and domestic realtime sheets are excluded.
- OAuth token issue/revoke, US stock REST/realtime sheets, and error codes are retained.
- Each API detail page extracts API ID, Method, production/mock domains, URL, and Content-Type near the top.
- Raw sheet tables keep Excel row numbers to make cross-checking against the original workbook easier.
- For paginated requests, check `cont-yn` and `next-key` in request/response headers.

## Included Sheets

| No. | Sheet | Range | Markdown |
| --- | --- | --- | --- |
| 1 | API 리스트 | A1:G340 | [Open](sheets/001-api.md) |
| 2 | au10001 | A1:G36 | [Open](sheets/002-au10001.md) |
| 3 | au10002 | A1:G33 | [Open](sheets/003-au10002.md) |
| 191 | usa01980 | A1:G45 | [Open](sheets/191-usa01980.md) |
| 192 | usa01990 | A1:G44 | [Open](sheets/192-usa01990.md) |
| 193 | usa06010 | A1:G45 | [Open](sheets/193-usa06010.md) |
| 194 | usa06011 | A1:G46 | [Open](sheets/194-usa06011.md) |
| 195 | usa06012 | A1:G47 | [Open](sheets/195-usa06012.md) |
| 196 | usa06013 | A1:G45 | [Open](sheets/196-usa06013.md) |
| 197 | usa06014 | A1:G45 | [Open](sheets/197-usa06014.md) |
| 198 | usa06015 | A1:G45 | [Open](sheets/198-usa06015.md) |
| 199 | usa06016 | A1:G45 | [Open](sheets/199-usa06016.md) |
| 200 | usa10098 | A1:G39 | [Open](sheets/200-usa10098.md) |
| 201 | usa10099 | A1:G39 | [Open](sheets/201-usa10099.md) |
| 202 | usa10100 | A1:G39 | [Open](sheets/202-usa10100.md) |
| 203 | usa10101 | A1:G35 | [Open](sheets/203-usa10101.md) |
| 204 | usa10102 | A1:G35 | [Open](sheets/204-usa10102.md) |
| 205 | usa10104 | A1:G39 | [Open](sheets/205-usa10104.md) |
| 206 | usa10105 | A1:G37 | [Open](sheets/206-usa10105.md) |
| 207 | usa20100 | A1:G73 | [Open](sheets/207-usa20100.md) |
| 208 | usa20101 | A1:G120 | [Open](sheets/208-usa20101.md) |
| 209 | usa20150 | A1:G39 | [Open](sheets/209-usa20150.md) |
| 210 | usa20151 | A1:G40 | [Open](sheets/210-usa20151.md) |
| 211 | usa20200 | A1:G34 | [Open](sheets/211-usa20200.md) |
| 212 | usa20201 | A1:G37 | [Open](sheets/212-usa20201.md) |
| 213 | usa20280 | A1:G37 | [Open](sheets/213-usa20280.md) |
| 214 | usa20281 | A1:G54 | [Open](sheets/214-usa20281.md) |
| 215 | usa20290 | A1:G40 | [Open](sheets/215-usa20290.md) |
| 216 | usa20291 | A1:G36 | [Open](sheets/216-usa20291.md) |
| 217 | usa20510 | A1:G51 | [Open](sheets/217-usa20510.md) |
| 218 | usa20511 | A1:G51 | [Open](sheets/218-usa20511.md) |
| 219 | usa20512 | A1:G50 | [Open](sheets/219-usa20512.md) |
| 220 | usa20520 | A1:G53 | [Open](sheets/220-usa20520.md) |
| 221 | usa20521 | A1:G53 | [Open](sheets/221-usa20521.md) |
| 222 | usa20530 | A1:G51 | [Open](sheets/222-usa20530.md) |
| 223 | usa20531 | A1:G51 | [Open](sheets/223-usa20531.md) |
| 224 | usa20540 | A1:G50 | [Open](sheets/224-usa20540.md) |
| 225 | usa20541 | A1:G50 | [Open](sheets/225-usa20541.md) |
| 226 | usa20550 | A1:G52 | [Open](sheets/226-usa20550.md) |
| 227 | usa20551 | A1:G52 | [Open](sheets/227-usa20551.md) |
| 228 | usa20570 | A1:G58 | [Open](sheets/228-usa20570.md) |
| 229 | usa20571 | A1:G58 | [Open](sheets/229-usa20571.md) |
| 230 | usa20590 | A1:G48 | [Open](sheets/230-usa20590.md) |
| 231 | usa20880 | A1:G42 | [Open](sheets/231-usa20880.md) |
| 232 | usa20881 | A1:G42 | [Open](sheets/232-usa20881.md) |
| 233 | usa20910 | A1:G53 | [Open](sheets/233-usa20910.md) |
| 234 | usa20911 | A1:G52 | [Open](sheets/234-usa20911.md) |
| 235 | usa20920 | A1:G54 | [Open](sheets/235-usa20920.md) |
| 236 | usa20921 | A1:G54 | [Open](sheets/236-usa20921.md) |
| 237 | usa20922 | A1:G54 | [Open](sheets/237-usa20922.md) |
| 238 | usa20930 | A1:G54 | [Open](sheets/238-usa20930.md) |
| 239 | usa20931 | A1:G54 | [Open](sheets/239-usa20931.md) |
| 240 | usa20932 | A1:G52 | [Open](sheets/240-usa20932.md) |
| 241 | usa20940 | A1:G59 | [Open](sheets/241-usa20940.md) |
| 242 | usa20941 | A1:G59 | [Open](sheets/242-usa20941.md) |
| 243 | usa20960 | A1:G45 | [Open](sheets/243-usa20960.md) |
| 244 | usa20961 | A1:G45 | [Open](sheets/244-usa20961.md) |
| 245 | usa20970 | A1:G55 | [Open](sheets/245-usa20970.md) |
| 246 | usa20971 | A1:G55 | [Open](sheets/246-usa20971.md) |
| 247 | usa20972 | A1:G55 | [Open](sheets/247-usa20972.md) |
| 248 | usa21670 | A1:G49 | [Open](sheets/248-usa21670.md) |
| 249 | usa21680 | A1:G49 | [Open](sheets/249-usa21680.md) |
| 250 | usa21690 | A1:G49 | [Open](sheets/250-usa21690.md) |
| 251 | usa21730 | A1:G54 | [Open](sheets/251-usa21730.md) |
| 252 | usa21731 | A1:G54 | [Open](sheets/252-usa21731.md) |
| 253 | usa21732 | A1:G54 | [Open](sheets/253-usa21732.md) |
| 254 | usa23000 | A1:G42 | [Open](sheets/254-usa23000.md) |
| 255 | usa23100 | A1:G49 | [Open](sheets/255-usa23100.md) |
| 256 | usa23400 | A1:G52 | [Open](sheets/256-usa23400.md) |
| 257 | usa23401 | A1:G52 | [Open](sheets/257-usa23401.md) |
| 258 | usa23402 | A1:G51 | [Open](sheets/258-usa23402.md) |
| 259 | usa24100 | A1:G57 | [Open](sheets/259-usa24100.md) |
| 260 | usa24101 | A1:G57 | [Open](sheets/260-usa24101.md) |
| 261 | usa24110 | A1:G59 | [Open](sheets/261-usa24110.md) |
| 262 | usa24111 | A1:G59 | [Open](sheets/262-usa24111.md) |
| 263 | usa24120 | A1:G55 | [Open](sheets/263-usa24120.md) |
| 264 | usa24121 | A1:G55 | [Open](sheets/264-usa24121.md) |
| 265 | usa24140 | A1:G56 | [Open](sheets/265-usa24140.md) |
| 266 | usa24141 | A1:G56 | [Open](sheets/266-usa24141.md) |
| 267 | usa24150 | A1:G52 | [Open](sheets/267-usa24150.md) |
| 268 | usa24151 | A1:G52 | [Open](sheets/268-usa24151.md) |
| 269 | usa24160 | A1:G53 | [Open](sheets/269-usa24160.md) |
| 270 | usa24161 | A1:G53 | [Open](sheets/270-usa24161.md) |
| 271 | usa24162 | A1:G52 | [Open](sheets/271-usa24162.md) |
| 272 | usa24200 | A1:G56 | [Open](sheets/272-usa24200.md) |
| 273 | usa24201 | A1:G56 | [Open](sheets/273-usa24201.md) |
| 274 | usa24210 | A1:G53 | [Open](sheets/274-usa24210.md) |
| 275 | usa24211 | A1:G53 | [Open](sheets/275-usa24211.md) |
| 276 | usa24220 | A1:G55 | [Open](sheets/276-usa24220.md) |
| 277 | usa24221 | A1:G55 | [Open](sheets/277-usa24221.md) |
| 278 | usa24290 | A1:G57 | [Open](sheets/278-usa24290.md) |
| 279 | usa24291 | A1:G60 | [Open](sheets/279-usa24291.md) |
| 280 | usa24300 | A1:G41 | [Open](sheets/280-usa24300.md) |
| 281 | usa26410 | A1:G46 | [Open](sheets/281-usa26410.md) |
| 282 | usa26411 | A1:G49 | [Open](sheets/282-usa26411.md) |
| 283 | usa26412 | A1:G50 | [Open](sheets/283-usa26412.md) |
| 284 | usa26413 | A1:G45 | [Open](sheets/284-usa26413.md) |
| 285 | usa26414 | A1:G46 | [Open](sheets/285-usa26414.md) |
| 286 | ust20000 | A1:G41 | [Open](sheets/286-ust20000.md) |
| 287 | ust20001 | A1:G41 | [Open](sheets/287-ust20001.md) |
| 288 | ust20002 | A1:G42 | [Open](sheets/288-ust20002.md) |
| 289 | ust20003 | A1:G36 | [Open](sheets/289-ust20003.md) |
| 290 | ust21050 | A1:G60 | [Open](sheets/290-ust21050.md) |
| 291 | ust21070 | A1:G70 | [Open](sheets/291-ust21070.md) |
| 292 | ust21100 | A1:G70 | [Open](sheets/292-ust21100.md) |
| 293 | ust21110 | A1:G44 | [Open](sheets/293-ust21110.md) |
| 294 | ust21111 | A1:G33 | [Open](sheets/294-ust21111.md) |
| 295 | ust21120 | A1:G42 | [Open](sheets/295-ust21120.md) |
| 296 | ust21121 | A1:G43 | [Open](sheets/296-ust21121.md) |
| 297 | ust21131 | A1:G42 | [Open](sheets/297-ust21131.md) |
| 298 | ust21132 | A1:G45 | [Open](sheets/298-ust21132.md) |
| 299 | ust21150 | A1:G66 | [Open](sheets/299-ust21150.md) |
| 300 | ust21160 | A1:G62 | [Open](sheets/300-ust21160.md) |
| 301 | ust21170 | A1:G59 | [Open](sheets/301-ust21170.md) |
| 302 | ust21180 | A1:G61 | [Open](sheets/302-ust21180.md) |
| 303 | ust21510 | A1:G57 | [Open](sheets/303-ust21510.md) |
| 304 | ust21530 | A1:G58 | [Open](sheets/304-ust21530.md) |
| 305 | ust21610 | A1:G55 | [Open](sheets/305-ust21610.md) |
| 306 | ust21620 | A1:G47 | [Open](sheets/306-ust21620.md) |
| 307 | ust21630 | A1:G49 | [Open](sheets/307-ust21630.md) |
| 308 | ust21640 | A1:G50 | [Open](sheets/308-ust21640.md) |
| 309 | ust21650 | A1:G59 | [Open](sheets/309-ust21650.md) |
| 310 | ust21660 | A1:G44 | [Open](sheets/310-ust21660.md) |
| 311 | ust21661 | A1:G44 | [Open](sheets/311-ust21661.md) |
| 312 | ust31300 | A1:G46 | [Open](sheets/312-ust31300.md) |
| 313 | ust31301 | A1:G37 | [Open](sheets/313-ust31301.md) |
| 314 | ust31302 | A1:G60 | [Open](sheets/314-ust31302.md) |
| 315 | ust31490 | A1:G62 | [Open](sheets/315-ust31490.md) |
| 335 | 미국주식 실시간 주문 확인(F4) | A1:G64 | [Open](sheets/335-f4.md) |
| 336 | 미국주식 실시간 체결(F5) | A1:G80 | [Open](sheets/336-f5.md) |
| 337 | 미국주식 실시간 체결가(FE) | A1:G62 | [Open](sheets/337-fe.md) |
| 338 | 미국주식 10호가(FT) | A1:G109 | [Open](sheets/338-10-ft.md) |
| 339 | 오류코드 | A1:C40 | [Open](sheets/339-sheet-339.md) |
