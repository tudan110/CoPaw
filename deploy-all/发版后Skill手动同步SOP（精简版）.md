# 已废止：发版后 Skill 手动同步 SOP

> **禁止执行下方旧 SOP。**它引用 `/app/.working.backup`，并以全目录差异决定删除项，不适用于当前 `/app/share/qwenpaw-seed` 和已有 PVC。
>
> 新发布流程由 Helm `managed-seed-sync` initContainer 自动执行镜像内的 `/usr/local/bin/sync_managed_seed.py`。人工检查可在 qwenpaw 容器内执行该脚本的无 `--apply` 模式；排障 apply 需显式确认。
>
> 下文保留仅供历史追溯。

> 适用场景：**新镜像已发布，但沿用了旧 PVC**，需要把镜像内 Skill 同步到 `/app/working`。
> 目标：**只同步 Skill 目录**，**不覆盖 `.env`**，**不动 settings/db/log/data 等运行时数据**。

---

## 0. 变量

```bash
NS=cnos-iomp
DEPLOY=qwenpaw
```

先确认 deployment 正常存在：

```bash
kubectl -n "$NS" get deploy "$DEPLOY"
kubectl -n "$NS" exec deploy/"$DEPLOY" -- sh -c 'ls -ld /app/.working.backup /app/working'
```

---

## 1. dry-run 看差异

```bash
cat > /tmp/qwenpaw-skill-dryrun.sh <<'SH'
set -eu
SRC=/app/.working.backup
DST=/app/working
TMPDIR=$(mktemp -d)
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup 0 1 2 3 15

list_roots() {
  if [ -d "$1/skill_pool" ]; then
    printf '%s\n' skill_pool
  fi
  if [ -d "$1/workspaces" ]; then
    find "$1/workspaces" -mindepth 2 -maxdepth 2 -type d -name skills | sed "s#^$1/##" | sort
  fi
}

collect_items() {
  root="$1"
  out="$2"
  if [ -d "$root" ]; then
    find "$root" -mindepth 1 ! -name .env -print | sed "s#^$root/##" | sort > "$out"
  else
    : > "$out"
  fi
}

list_roots "$SRC" > "$TMPDIR/src_roots"
list_roots "$DST" > "$TMPDIR/dst_roots"
cat "$TMPDIR/src_roots" "$TMPDIR/dst_roots" | sort -u > "$TMPDIR/all_roots"

add=0
update=0
delete=0

while IFS= read -r rel_root; do
  [ -n "$rel_root" ] || continue
  src_root="$SRC/$rel_root"
  dst_root="$DST/$rel_root"
  collect_items "$src_root" "$TMPDIR/src_items"
  collect_items "$dst_root" "$TMPDIR/dst_items"

  comm -23 "$TMPDIR/src_items" "$TMPDIR/dst_items" > "$TMPDIR/add_items"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    printf 'ADD    %s/%s\n' "$rel_root" "$rel"
    add=$((add + 1))
  done < "$TMPDIR/add_items"

  comm -13 "$TMPDIR/src_items" "$TMPDIR/dst_items" > "$TMPDIR/del_items"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    printf 'DELETE %s/%s\n' "$rel_root" "$rel"
    delete=$((delete + 1))
  done < "$TMPDIR/del_items"

  comm -12 "$TMPDIR/src_items" "$TMPDIR/dst_items" > "$TMPDIR/both_items"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    sp="$src_root/$rel"
    dp="$dst_root/$rel"
    if [ -d "$sp" ] && [ -d "$dp" ]; then
      continue
    fi
    if [ -f "$sp" ] && [ -f "$dp" ]; then
      if ! cmp -s "$sp" "$dp"; then
        printf 'UPDATE %s/%s\n' "$rel_root" "$rel"
        update=$((update + 1))
      fi
    else
      printf 'UPDATE %s/%s\n' "$rel_root" "$rel"
      update=$((update + 1))
    fi
  done < "$TMPDIR/both_items"
done < "$TMPDIR/all_roots"

printf '%s\n' '--- SUMMARY ---'
printf 'ADD: %s\n' "$add"
printf 'UPDATE: %s\n' "$update"
printf 'DELETE: %s\n' "$delete"
SH

kubectl -n "$NS" exec -i deploy/"$DEPLOY" -- sh < /tmp/qwenpaw-skill-dryrun.sh
rm -f /tmp/qwenpaw-skill-dryrun.sh
```

**看结果：**
- `ADD` = 镜像里新增、PVC 里没有
- `UPDATE` = 两边都有，但内容不同
- `DELETE` = PVC 残留、镜像里已没有

---

## 2. 正式同步

```bash
cat > /tmp/qwenpaw-skill-sync.sh <<'SH'
set -eu
SRC=${SRC:-/app/.working.backup}
DST=${DST:-/app/working}
TMPDIR=$(mktemp -d)
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup 0 1 2 3 15

list_roots() {
  if [ -d "$1/skill_pool" ]; then
    printf '%s\n' skill_pool
  fi
  if [ -d "$1/workspaces" ]; then
    find "$1/workspaces" -mindepth 2 -maxdepth 2 -type d -name skills | sed "s#^$1/##" | sort
  fi
}

collect_items() {
  root="$1"
  out="$2"
  if [ -d "$root" ]; then
    find "$root" -mindepth 1 ! -name .env -print | sed "s#^$root/##" | sort > "$out"
  else
    : > "$out"
  fi
}

copy_item() {
  src="$1"
  dst="$2"
  if [ -d "$src" ]; then
    mkdir -p "$dst"
  else
    mkdir -p "$(dirname "$dst")"
    cp -f "$src" "$dst"
  fi
}

delete_item() {
  path="$1"
  if [ -d "$path" ]; then
    rm -rf "$path"
  else
    rm -f "$path"
  fi
}

list_roots "$SRC" > "$TMPDIR/src_roots"
list_roots "$DST" > "$TMPDIR/dst_roots"
cat "$TMPDIR/src_roots" "$TMPDIR/dst_roots" | sort -u > "$TMPDIR/all_roots"

add=0
update=0
delete=0

while IFS= read -r rel_root; do
  [ -n "$rel_root" ] || continue
  src_root="$SRC/$rel_root"
  dst_root="$DST/$rel_root"
  collect_items "$src_root" "$TMPDIR/src_items"
  collect_items "$dst_root" "$TMPDIR/dst_items"

  comm -23 "$TMPDIR/src_items" "$TMPDIR/dst_items" > "$TMPDIR/add_items"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    copy_item "$src_root/$rel" "$dst_root/$rel"
    printf 'ADD    %s/%s\n' "$rel_root" "$rel"
    add=$((add + 1))
  done < "$TMPDIR/add_items"

  comm -12 "$TMPDIR/src_items" "$TMPDIR/dst_items" > "$TMPDIR/both_items"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    sp="$src_root/$rel"
    dp="$dst_root/$rel"
    if [ -d "$sp" ] && [ -d "$dp" ]; then
      continue
    fi
    if [ -f "$sp" ] && [ -f "$dp" ]; then
      if ! cmp -s "$sp" "$dp"; then
        copy_item "$sp" "$dp"
        printf 'UPDATE %s/%s\n' "$rel_root" "$rel"
        update=$((update + 1))
      fi
    else
      delete_item "$dp"
      copy_item "$sp" "$dp"
      printf 'UPDATE %s/%s\n' "$rel_root" "$rel"
      update=$((update + 1))
    fi
  done < "$TMPDIR/both_items"

  comm -13 "$TMPDIR/src_items" "$TMPDIR/dst_items" > "$TMPDIR/del_items"
  while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    delete_item "$dst_root/$rel"
    printf 'DELETE %s/%s\n' "$rel_root" "$rel"
    delete=$((delete + 1))
  done < "$TMPDIR/del_items"
done < "$TMPDIR/all_roots"

printf '%s\n' '--- SUMMARY ---'
printf 'ADD: %s\n' "$add"
printf 'UPDATE: %s\n' "$update"
printf 'DELETE: %s\n' "$delete"
SH

kubectl -n "$NS" exec -i deploy/"$DEPLOY" -- sh < /tmp/qwenpaw-skill-sync.sh
rm -f /tmp/qwenpaw-skill-sync.sh
```

---

## 3. 再跑一次 dry-run 复核

重复执行**第 1 步**。理想结果：

```text
ADD: 0
UPDATE: 0
DELETE: 0
```

---

## 4. 重启 qwenpaw

```bash
kubectl -n "$NS" rollout restart deploy/"$DEPLOY"
kubectl -n "$NS" rollout status deploy/"$DEPLOY" --timeout=300s
```

---

## 5. 注意事项

- **不会覆盖 `.env`**
- **会同步 `.env.example`**（它属于 skill 发布物）
- **不会动** `settings.db`、知识库 data、日志、缓存、数据库等运行时数据
- 如果 dry-run 输出很多 `__pycache__` 的 `DELETE`，这是正常的旧残留清理
