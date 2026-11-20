#!/bin/sh
# สำรองฐานข้อมูล POS WAI ทุกคืน เก็บ 14 วัน
#
# ก๊อปไฟล์ .db ตรง ๆ ตอนแอปยังทำงานอยู่ได้ไฟล์ที่ขาดกลางคัน เพราะ SQLite
# เขียนค้างอยู่ จึงใช้ .backup ของ sqlite3 ผ่าน python ในคอนเทนเนอร์แทน
# ซึ่งอ่านแบบล็อกถูกต้องและได้ไฟล์ที่เปิดได้เสมอ
#
# กู้คืน: docker compose down · แตก tar ลงในวอลุ่ม poswai_poswai_data · up
set -eu

CONTAINER=poswai-poswai-1
OUT=/docker/poswai/backups
KEEP_DAYS=14
STAMP=$(date +%Y%m%d-%H%M)

mkdir -p "$OUT"

# -i จำเป็น ไม่งั้น python ไม่ได้รับสคริปต์ทาง stdin แล้วเงียบ ๆ ไม่ทำอะไร
docker exec -i "$CONTAINER" python - <<'PY'
import os
import shutil
import sqlite3

STAGE = "/data/_backup_stage"
shutil.rmtree(STAGE, ignore_errors=True)
os.makedirs(STAGE + "/shops", exist_ok=True)

def copy(src, dst):
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as source, \
            sqlite3.connect(dst) as target:
        source.backup(target)

count = 0
for name in sorted(os.listdir("/data")):
    if name.endswith(".db"):
        copy(f"/data/{name}", f"{STAGE}/{name}")
        count += 1
shops = "/data/shops"
if os.path.isdir(shops):
    for name in sorted(os.listdir(shops)):
        if name.endswith(".db"):
            copy(f"{shops}/{name}", f"{STAGE}/shops/{name}")
            count += 1
print(f"staged {count} databases")
PY

docker exec "$CONTAINER" tar czf - -C /data _backup_stage > "$OUT/nightly-$STAMP.tar.gz"
docker exec "$CONTAINER" rm -rf /data/_backup_stage

# ไฟล์ว่างแปลว่าสำรองไม่สำเร็จ อย่าเก็บไว้ให้เข้าใจผิดว่ามีสำรองแล้ว
# tar เปล่ามีขนาดราว 45 ไบต์ ซึ่งผ่าน -s ไปได้ จึงต้องดูว่ามีไฟล์ .db อยู่ข้างในจริง
if ! tar tzf "$OUT/nightly-$STAMP.tar.gz" 2>/dev/null | grep -q '\.db$'; then
  echo "สำรองล้มเหลว: ไม่มีฐานข้อมูลอยู่ในไฟล์" >&2
  rm -f "$OUT/nightly-$STAMP.tar.gz"
  exit 1
fi

find "$OUT" -name 'nightly-*.tar.gz' -mtime +$KEEP_DAYS -delete
echo "$(date '+%F %T') สำรองสำเร็จ $(du -h "$OUT/nightly-$STAMP.tar.gz" | cut -f1) -> nightly-$STAMP.tar.gz"
