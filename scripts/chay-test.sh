#!/usr/bin/env bash
# Chạy cả NĂM bộ test của repo và in một bảng tổng kết.
#
#   scripts/chay-test.sh              # chạy hết, in bảng
#   scripts/chay-test.sh --sach       # đo ở worktree sạch tại HEAD (khuyên dùng)
#   scripts/chay-test.sh 3            # chỉ chạy bộ 3
#
# Vì sao có file này: năm bộ nằm ở năm chỗ, mỗi bộ một lệnh riêng, và bốn cái
# bẫy đã ăn thời gian của người khác (xem docs/chay-test-toan-du-an.md).  Người
# nhớ ba bộ rồi kết luận "đợt sạch" là chuyện đã xảy ra thật.  Một lệnh thì
# không nhớ nhầm được.
#
# Mã thoát: 0 khi không bộ nào đỏ vì code.  Bộ 5 thiếu ``pytest`` được tính là
# MÔI TRƯỜNG và KHÔNG làm hỏng mã thoát — nhưng chỉ đúng lý do ấy thôi.
#
# Ba kiểu "xanh giả" bảng này chặn, cả ba đều đã xảy ra thật:
#   - bộ chết trước khi in tổng kết  → không số nào để đếm, đọc thành 0 đỏ;
#   - bộ chạy 0 bài rồi in OK        → xanh mà rỗng (bộ 5 nằm đúng đây);
#   - bộ 3 nhận đường dẫn thư mục    → MODULE_NOT_FOUND, in "# fail 1".
# Nên ngoài số đọc từ log còn phải hỏi mã thoát, và chặn cả trường hợp 0 bài.
#
# Số bài đỏ đọc từ log, CÒN mã thoát của từng bộ thì đọc riêng: một bộ chết
# trước khi in được dòng tổng kết không để lại số nào để đếm, và bảng sẽ đọc
# thành 0 đỏ nếu chỉ tin vào log.

set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
SACH=0
CHON=""

for arg in "$@"; do
  case "$arg" in
    --sach) SACH=1 ;;
    1|2|3|4|5) CHON="$CHON $arg" ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Không hiểu đối số: $arg (dùng --help)" >&2; exit 2 ;;
  esac
done

if [ ! -x "$PY" ]; then
  echo "Không thấy $PY — dựng .venv trước đã." >&2
  exit 2
fi
if ! command -v node >/dev/null 2>&1; then
  echo "Không thấy node trong PATH; bộ 3 sẽ không chạy được." >&2
  exit 2
fi

# --sach: đo ở worktree sạch tại HEAD.  Cây làm việc có thể đang có file chưa
# commit của người khác đỡ hộ, và con số đo được ở đó không nói lên điều gì về
# commit sắp đẩy đi.  Đã có lần một nhánh suýt đi với 16 bài đỏ vì đo nhầm chỗ.
if [ "$SACH" = "1" ]; then
  WT="$(mktemp -d)/wt"
  echo "Dựng worktree sạch tại $(git -C "$ROOT" rev-parse --short HEAD) → $WT"
  git -C "$ROOT" worktree add -q --detach "$WT" HEAD || exit 2
  # .venv và node_modules không đi theo worktree; dùng lại của cây gốc.
  trap 'git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1' EXIT
  DIR="$WT"
else
  DIR="$ROOT"
fi

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"; [ "$SACH" = "1" ] && git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1' EXIT

declare -a TEN TONG XANH DO GHICHU RC MIENTRU PHU
LOI=0

muon() { # bộ $1 có được chọn không
  [ -z "$CHON" ] && return 0
  case " $CHON " in *" $1 "*) return 0 ;; *) return 1 ;; esac
}

# ---- Python: đọc "Ran N tests" và "OK"/"FAILED" ở cuối stderr ----
tom_tat_python() {
  local log="$1" idx="$2"
  local ran dong bai
  ran="$(grep -Eo '^Ran [0-9]+ test' "$log" | tail -1 | grep -Eo '[0-9]+')"
  [ -z "$ran" ] && ran=0
  # Đếm theo BÀI, không theo DÒNG.  Mỗi subTest hỏng in một dòng FAIL/ERROR
  # riêng, còn "Ran N tests" đếm theo bài — trộn hai đơn vị lại thì cột xanh ra
  # số ÂM (đo thật: log 1 bài với 5 subtest đỏ cho xanh = -4).  Bảng này là chỗ
  # duy nhất trả lời "cả năm bộ có xanh không"; in một lần số âm là mất tin cả
  # bảng.  Hai trường đầu của dòng là tên bài và id có chấm, giống nhau ở mọi
  # dòng subTest của cùng một bài, nên sort -u gộp chúng lại đúng một bài.
  dong="$(grep -cE '^(FAIL|ERROR): ' "$log" || true)"
  bai="$(awk '/^(FAIL|ERROR): /{print $2, $3}' "$log" | sort -u | grep -c . || true)"
  : "${dong:=0}" "${bai:=0}"
  TONG[$idx]="$ran"; DO[$idx]="$bai"
  XANH[$idx]="$(( ran > bai ? ran - bai : 0 ))"
  # Chênh lệch nói ra chứ không nuốt: 1 bài đỏ vì 5 subtest là 5 chỗ phải sửa.
  if [ "$dong" -gt "$bai" ]; then PHU[$idx]="($dong dòng FAIL/ERROR, có subTest)"; fi
}

# ---- bộ 1 ----
if muon 1; then
  ( cd "$DIR" && "$PY" -m unittest discover -s tests -p 'test_*.py' ) >"$TMP/1.log" 2>&1
  RC[1]=$?
  tom_tat_python "$TMP/1.log" 1; TEN[1]="1. tests/"
  GHICHU[1]="$(grep -c 'OutboundNetworkBlocked' "$TMP/1.log") lần bị chốt mạng chặn"
fi

# ---- bộ 2 ----
if muon 2; then
  ( cd "$DIR/automation_center" && "$PY" -m unittest discover -s tests -p 'test_*.py' ) >"$TMP/2.log" 2>&1
  RC[2]=$?
  tom_tat_python "$TMP/2.log" 2; TEN[2]="2. automation_center python"; GHICHU[2]=""
fi

# ---- bộ 3: PHẢI dùng glob *.test.mjs, không dùng đường dẫn thư mục ----
# Đưa thư mục vào thì node coi `tests` là một module để nạp, chết với
# MODULE_NOT_FOUND, rồi in "# fail 1" như thể chỉ có một bài đỏ.
if muon 3; then
  ( cd "$DIR" && node --test --experimental-sqlite automation_center/tests/*.test.mjs ) >"$TMP/3.log" 2>&1
  RC[3]=$?
  TEN[3]="3. automation_center node"
  TONG[3]="$(grep -Eo '^# tests [0-9]+' "$TMP/3.log" | tail -1 | grep -Eo '[0-9]+')"
  XANH[3]="$(grep -Eo '^# pass [0-9]+' "$TMP/3.log" | tail -1 | grep -Eo '[0-9]+')"
  DO[3]="$(grep -Eo '^# fail [0-9]+' "$TMP/3.log" | tail -1 | grep -Eo '[0-9]+')"
  : "${TONG[3]:=0}" "${XANH[3]:=0}" "${DO[3]:=0}"
  GHICHU[3]="$(grep -E '^not ok' "$TMP/3.log" | sed 's/ *#.*//' | tr '\n' ' ')"
fi

# ---- bộ 4, 5 ----
if muon 4; then
  ( cd "$DIR/_bmad/core/bmad-init/scripts" && "$PY" -m unittest discover -s tests -p 'test_*.py' ) >"$TMP/4.log" 2>&1
  RC[4]=$?
  tom_tat_python "$TMP/4.log" 4; TEN[4]="4. bmad-init"; GHICHU[4]=""
fi

# ---- bộ 5: chạy bằng pytest, KHÔNG phải unittest ----
# Bộ này viết bằng pytest thật (`@pytest.fixture`).  `unittest discover` không
# gom được bài nào của nó: máy thiếu pytest thì đỏ một bài "lỗi import", còn
# máy CÓ pytest thì in "Ran 0 tests ... OK" — xanh trong khi chạy rỗng.  Cả 33
# bài chưa từng chạy bằng lệnh cũ.  Đo được, xem docs/chay-test-toan-du-an.md.
if muon 5; then
  TEN[5]="5. bmad-distillator"
  ( cd "$DIR/_bmad/core/bmad-distillator/scripts" && "$PY" -m pytest tests -q ) >"$TMP/5.log" 2>&1
  RC[5]=$?
  # Neo chặt hai đầu.  Mẫu cũ ("No module named '?pytest'?") có dấu nháy TUỲ
  # CHỌN nên khớp luôn mọi plugin thiếu tên bắt đầu bằng pytest —
  # 'pytest_asyncio', 'pytest_cov' đều lọt, và bộ 5 chết vì thiếu plugin sẽ bị
  # đọc thành MÔI TRƯỜNG rồi thoát 0.  Dòng thật là ".../python: No module
  # named pytest", không có nháy và không có gì đứng sau.
  if grep -qE ": No module named pytest$" "$TMP/5.log"; then
    TONG[5]=0; XANH[5]=0; DO[5]=0; MIENTRU[5]=1
    GHICHU[5]="MÔI TRƯỜNG — .venv thiếu extra [dev]; sửa: pip install -e \".[dev]\""
  else
    XANH[5]="$(grep -Eo '[0-9]+ passed' "$TMP/5.log" | tail -1 | grep -Eo '[0-9]+')"
    D5F="$(grep -Eo '[0-9]+ failed' "$TMP/5.log" | tail -1 | grep -Eo '[0-9]+')"
    D5E="$(grep -Eo '[0-9]+ error' "$TMP/5.log" | tail -1 | grep -Eo '[0-9]+')"
    : "${XANH[5]:=0}" "${D5F:=0}" "${D5E:=0}"
    DO[5]="$((D5F + D5E))"; TONG[5]="$((XANH[5] + DO[5]))"; GHICHU[5]=""
  fi
fi

echo
echo "================== TỔNG KẾT =================="
printf '%-30s %6s %6s %5s  %s\n' "Bộ" "tổng" "xanh" "đỏ" "ghi chú"
for i in 1 2 3 4 5; do
  muon "$i" || continue
  [ -z "${TEN[$i]:-}" ] && continue
  # Đọc log để đếm bài đỏ là chưa đủ.  Bộ chết TRƯỚC khi kịp in dòng tổng kết
  # thì không có số nào để đọc, và chỗ này từng in "Không bộ nào đỏ vì code"
  # rồi thoát 0 — xanh giả, đúng cái mà cả file này sinh ra để chặn.  Nên hỏi
  # thêm mã thoát: khác 0 mà không đọc ra bài đỏ nào thì là đỏ, không phải sạch.
  if [ "${MIENTRU[$i]:-0}" = "1" ]; then
    : # đã phân loại MÔI TRƯỜNG ở trên, không tính vào mã thoát
  elif [ "${RC[$i]:-0}" != "0" ] && [ "${DO[$i]}" = "0" ]; then
    GHICHU[$i]="mã thoát ${RC[$i]} nhưng không đọc ra bài đỏ nào — đọc $TMP/$i.log"
    DO[$i]="?"
  elif [ "${TONG[$i]}" = "0" ]; then
    # Chạy 0 bài mà vẫn thoát 0 là xanh rỗng, không phải sạch.  Bộ 5 từng ở
    # đúng trạng thái ấy suốt: lệnh cũ gom được 0 bài rồi in OK.
    GHICHU[$i]="chạy 0 bài — không gom được bài nào, đọc $TMP/$i.log"
    DO[$i]="?"
  fi
  printf '%-30s %6s %6s %5s  %s\n' "${TEN[$i]}" "${TONG[$i]}" "${XANH[$i]}" "${DO[$i]}" "${GHICHU[$i]:-}${PHU[$i]:+ ${PHU[$i]}}"
  [ "${DO[$i]}" != "0" ] && LOI=1
done
echo "Log đầy đủ: $TMP  (log bị xoá khi lệnh này kết thúc — copy ra nếu cần)"
echo
if [ "$LOI" = "0" ]; then
  echo "Không bộ nào đỏ vì code."
else
  echo "CÓ BÀI ĐỎ. Phân loại trước khi kết luận: LỖI CODE · CHƯA CÀI · TEST SAI · MÔI TRƯỜNG."
  echo "Đừng sửa test cho xanh — xem docs/chay-test-toan-du-an.md."
fi
exit "$LOI"
