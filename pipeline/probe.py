"""임시 진단 (머지 전에 삭제)."""
import re
import requests

E = "https://ecos.bok.or.kr/api"
for a, b in ((11, 20), (21, 30), (31, 40)):
    t = requests.get(f"{E}/StatisticItemList/sample/json/kr/{a}/{b}/901Y027", timeout=20).text
    print(a, re.findall(r'"ITEM_CODE":"[^"]+","ITEM_NAME":"[^"]+"|"CYCLE":"\w"', t)[:30])
for code in ("901Y118/M/202509/202609/T002", "901Y027/M/202601/202609/I61BC", "901Y027/M/202601/202609/I61E"):
    t = requests.get(f"{E}/StatisticSearch/sample/json/kr/1/10/{code}", timeout=20).text
    print(code, re.findall(r'"ITEM_NAME1":"[^"]+"|"UNIT_NAME":"[^"]+"|"TIME":"[^"]+","DATA_VALUE":"[^"]+"', t)[:14] or t[:200])
