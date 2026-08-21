# 已废止：发版后 Skill 手动同步命令

> **禁止执行本文后续的 Shell 同步命令。**它们引用已移除的 `/app/.working.backup`，并会对整个目录做删除判断，可能误删 PVC 中的知识库数据、用户自装 Skill 或 `skill_pool`。
>
> 当前发布使用 Helm `managed-seed-sync` initContainer 自动同步 `/app/share/qwenpaw-seed` 的受管文件。人工检查请使用：
>
> ```bash
> qwenpaw deploy sync-managed --dry-run
> ```
>
> 人工 apply 仅在明确排障时使用：
>
> ```bash
> qwenpaw deploy sync-managed --apply --yes
> ```
>
> 下文保留仅供追溯旧流程，不能作为当前操作指南。

## 背景

当智观平台使用**新镜像重新部署**，但**沿用旧 PVC** 时，`/app/working/` 中的工作区文件不会自动更新。
这时可能出现：

- PVC 中的 skill 文件仍是旧版本
- 镜像内 skill 已更新，但运行时仍使用旧文件
- PVC 中残留历史调试脚本、临时文件、已废弃说明文件

如果是**首次部署**、PVC 尚未创建，则不存在这个问题；
如果是**复用旧 PVC 的升级发布**，则建议在发版后补做一次 **Skill 文件同步**。

本文档提供一套**不依赖 Python / AI，只依赖 shell 工具**的手工同步命令。

---

## 目标

在 **qwenpaw 容器内部**，把镜像内置目录：

- 源目录：`/app/.working.backup/`

同步到 PVC 挂载目录：

- 目标目录：`/app/working/`

但**只处理 Skill 相关目录**，不改动运行时数据。

---

## 同步原则

1. **只同步 Skill 相关目录**  
   仅处理：
   - `skill_pool/`
   - `workspaces/*/skills/`

2. **不覆盖 `.env` 文件**  
   `.env` 属于环境配置，必须保留目标环境现状。

3. **保留 `.env.example`**  
   `.env.example` 属于 skill 发布物的一部分，应该随镜像同步。

4. **允许删除旧 Skill 残留文件**  
   若某个 skill 文件在新镜像中已不存在，则从 PVC 对应 skill 目录中删除。

5. **不处理非 Skill 数据**  
   不改动以下内容：
   - `settings.db`
   - 知识库 data 数据
   - 日志
   - 上传文件
   - 缓存
   - 数据库类持久化内容
   - 其他业务运行时文件

6. **先 dry-run，再正式执行**  
   先看差异预览，再执行正式同步，最后再校验一次。

---

## 适用场景

适用于：

- 新镜像已发布
- Kubernetes / k3s 部署复用了旧 PVC
- skill 脚本、说明、配置文件在镜像中有更新
- 需要清理 PVC 中旧版本遗留文件

不适用于：

- 首次部署、PVC 尚未初始化
- 仅修改运行时配置（如 `.env`、数据库内容）
- 想直接重置整个工作区（那是删 PVC 的场景，不是 skill 同步）

---

## 执行前准备

以下命令默认以 qwenpaw deployment 为目标：

```bash
NS=cnos-iomp
DEPLOY=qwenpaw
```

先确认 deployment 存在：

```bash
kubectl -n "$NS" get deploy "$DEPLOY"
```

再确认源/目标目录都存在：

```bash
kubectl -n "$NS" exec deploy/"$DEPLOY" -- sh -c 'ls -ld /app/.working.backup /app/working'
```

---

## 第一步：dry-run 差异预览

下面这条命令**不会修改任何文件**，只会输出：

- `ADD`：镜像里有、PVC 里没有
- `UPDATE`：两边都有，但内容不同
- `DELETE`：PVC 里有、镜像里没有

> 说明：这份脚本已在公网演示环境实际验证可执行。

```bash
cat > /tmp/qwenpaw-skill-dryrun.sh <<'SH'
set -eu
SRC=/app/.working.backup
DST=/app/working
TMPDIR=$(mktemp -d)
cleanup() {
  rm -rf "$TMPDIR"
}
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

---

## 第二步：正式执行同步

下面这条命令会：

- 自动创建缺失目录
- 复制新增文件
- 覆盖更新文件
- 删除镜像里已不存在的旧 skill 文件
- 跳过所有 `.env` 文件

```bash
cat > /tmp/qwenpaw-skill-sync.sh <<'SH'
set -eu
SRC=${SRC:-/app/.working.backup}
DST=${DST:-/app/working}
TMPDIR=$(mktemp -d)
cleanup() {
  rm -rf "$TMPDIR"
}
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

## 第三步：同步后再次校验

正式同步完成后，再跑一次**第一步 dry-run**。

理想情况下，结果应该是：

- `ADD: 0`
- `UPDATE: 0`
- `DELETE: 0`

也就是 skill 相关目录已经一致。

---

## 第四步：建议重启 qwenpaw

虽然很多 skill 文件是热更新可见的，但为了避免旧进程仍缓存旧内容，建议同步完成后滚动重启一次：

```bash
kubectl -n "$NS" rollout restart deploy/"$DEPLOY"
kubectl -n "$NS" rollout status deploy/"$DEPLOY" --timeout=300s
```

---

## 同步结果记录建议

建议同事执行后把以下信息贴回工单或发布记录：

1. dry-run 摘要（ADD / UPDATE / DELETE 数量）
2. 正式同步摘要
3. 同步后复核结果（是否全部归零）
4. 是否执行了 rollout restart
5. 如有跳过项或异常项，写明原因

---

## 风险说明

- 本文档**不会删除整个 PVC**，只处理 skill 相关目录
- `.env` 文件会被保留，不会覆盖
- `.env.example` 会跟随镜像同步，这是预期行为
- 如果某些旧文件不在 skill 目录下，本文档不会擅自处理
- 如果知识库 `data/`、数据库、日志等运行时文件有差异，属于正常现象，不在本次同步范围内

---

## 实测说明

这份纯 shell 版命令已在公网演示环境 `82.156.83.38` 的 `qwenpaw` 容器中验证：

- 容器内可用工具包括：`sh`、`find`、`cmp`、`cp`、`rm`、`diff`、`mktemp`、`sort`、`comm`、`sed`、`dirname`、`mkdir`
- dry-run 实测能正确输出 `UPDATE` / `DELETE` 明细
- 正式同步脚本已通过 `sh -n` 语法检查

---

## 适合发给同事的简版说明

```text
这是发版后 skill 手动同步命令（纯 shell 版），只处理 /app/.working.backup 和 /app/working 之间的 skill 目录差异，不动 settings.db、知识库数据、日志、缓存等运行时数据，也不会覆盖 .env。
请按顺序执行：
1. 先跑 dry-run 看差异
2. 再跑正式同步
3. 再跑一次 dry-run 确认归零
4. 最后 rollout restart qwenpaw
```
