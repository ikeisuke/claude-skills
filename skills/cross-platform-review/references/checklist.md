# Cross-Platform Review Checklist

macOS (BSD) と Linux (GNU, WSL2 含む) で挙動が変わる代表パターン。
差分に該当する記述があれば BLOCKER / HIGH / MED に分類して指摘する。

## 目次

1. [BSD / GNU コマンド差](#1-bsd--gnu-コマンド差)
2. [シェル組み込みの差](#2-シェル組み込みの差)
3. [パスの違い](#3-パスの違い)
4. [macOS 専用コマンド](#4-macos-専用コマンド)
5. [Linux 専用コマンド](#5-linux-専用コマンド)
6. [WSL2 特有の処理](#6-wsl2-特有の処理)
7. [Brewfile / セットアップスクリプトの対称性](#7-brewfile--セットアップスクリプトの対称性)
8. [zsh モジュール構成（dotfiles 想定）](#8-zsh-モジュール構成dotfiles-想定)
9. [シェバン (`#!`)](#9-シェバン-)
10. [ファイルシステム差](#10-ファイルシステム差)
11. [重要度の判定基準](#重要度の判定基準)

---

## 1. BSD / GNU コマンド差

### `sed`
- **`sed -i`**: macOS BSD は `-i` の直後に **拡張子引数が必須**（空文字列でもよい）。GNU は引数なしを許容
  - NG: `sed -i 's/foo/bar/' file`（macOS で「extra argument」エラー）
  - NG（GNU でしか動かない）: `sed -i'' -e 's/foo/bar/' file`（BSD は `-i` の引数として `''` を取れずエラー）
  - **両対応の推奨形**: バックアップ拡張子を明示し、後で消す
    ```bash
    sed -i.bak 's/foo/bar/' file && rm -f file.bak
    ```
  - macOS 専用なら: `sed -i '' 's/foo/bar/' file`（`-i` と `''` の間に空白が必要）
  - 別解: `gsed`（GNU sed）を Brewfile で導入し、両対応スクリプトでは GNU 互換を選ぶ
- **拡張正規表現**: BSD は `-E`、GNU は `-r` だが、GNU は `-E` も受け付ける → **常に `-E` を使う**
- **`\s`, `\b` 等の Perl 拡張**: BSD では非対応。POSIX 文字クラス（`[[:space:]]` 等）に置き換える

### `date`
- **`-d` フラグ**: GNU 専用（任意の日付文字列をパース）。macOS BSD `date` は `-d` を受け付けず usage エラーになる
  - NG（macOS で usage エラー）: `date -d '1 day ago'`
  - OK 両対応: macOS は `date -v-1d`、GNU は `date -d '1 day ago'` → OS 判定して分岐
  - 推奨: 簡単な日付なら `date +%Y-%m-%d` だけで済むよう設計を見直す
- **タイムゾーン指定**: macOS は `TZ=Asia/Tokyo date`、GNU も同形式で動く（共通）

### `stat`
- **フォーマット指定子の差**:
  - BSD: `stat -f '%z' file`（サイズ）
  - GNU: `stat -c '%s' file`
- 両対応: `wc -c < file` でサイズ取得、`ls -l` を `awk` でパースする等、`stat` を避ける
- もしくは OS 分岐で `stat` のフラグを切り替える

### `mktemp`
- **テンプレート**: macOS BSD は引数なし / `-t prefix` で `$TMPDIR` 配下にファイル作成（場所は OS 依存）。GNU は `mktemp /tmp/foo.XXXXXX` のように **テンプレートが必須**
  - 両 OS で動くが作成先パスが揃わない: `mktemp` 単独は macOS では `$TMPDIR/tmp.XXXXXXXX` を生成、GNU は usage エラー
  - **両対応の推奨形**: フルパステンプレートを明示する
    ```bash
    mktemp /tmp/myapp.XXXXXX  # X は 6 個以上
    ```
  - 補足: GNU の `mktemp -t prefix.XXXXXX` は GNU 専用挙動（テンプレート必須かつ `-t` で `$TMPDIR` 経由）。macOS BSD の `-t prefix` とはセマンティクスが異なる
- **`-d` (ディレクトリ作成)**: 両対応

### `readlink`
- **`-f` フラグ**: macOS BSD `readlink` の `-f` は環境依存（macOS 12 以降は `-f` をサポート、それ以前の Mac では未対応）。CI / 古い環境を前提にするなら避ける
  - NG（古い macOS / 一部の最小環境で失敗）: `readlink -f script.sh`
  - **両対応の推奨形**:
    ```bash
    # 1) Python 経由（最も移植性が高い）
    python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"

    # 2) coreutils の greadlink（Brew で `coreutils` を入れると greadlink が使える）
    greadlink -f "$1"

    # 3) シェルだけで完結させる自前ループ
    target="$1"
    while [ -L "$target" ]; do target=$(readlink "$target"); done
    ```

### `find`
- **`-regex`**: BSD と GNU で正規表現方言が違う
  - GNU: デフォルトは emacs 風、`-regextype posix-extended` で ERE
  - BSD: 常に basic regex、`-E` で ERE
- **`-printf`**: GNU 専用。BSD には無し → `-exec stat ...` 等で代替

### `grep`
- **`-P` (PCRE)**: GNU 拡張。BSD `grep` は非対応
  - NG: `grep -P '\d+' file`
  - OK: `grep -E '[0-9]+' file`（ERE で代替できることが多い）
- **`-r` の挙動差**: GNU は隠しファイルも含む、BSD はバージョン依存。明示的に `--include` / `--exclude` で制御

### `awk`
- **GNU 拡張（`gensub`, `gsub` の戻り値, `length` の引数）**: BSD `awk`（`nawk`）では動かない
  - 推奨: ポータブル POSIX awk の範囲で書く。GNU 専用機能を使うなら `gawk` を明示

### `xargs`
- **`-r` (`--no-run-if-empty`)**: GNU 専用フラグ。空入力時の挙動は OS で **逆向きに非対称**:
  - **GNU `xargs`**: 空入力でも utility を **1 回実行**する（POSIX-2017 では implementation-defined だが GNU はこの挙動）。GNU info manual: "By default, xargs runs the command once even if there is no input". `-r` で抑制可能
  - **macOS BSD `xargs`**: 空入力では utility を実行しない（man page: "the FreeBSD version of xargs does not run the utility argument on empty input"）。`-r` は互換性のため受け付けるが no-op
  - 結果: `find ... | xargs cmd` で 0 件のとき、Linux では `cmd` が空引数で 1 回呼ばれ、macOS では呼ばれない
  - 注意: `-0` (NUL 区切り) は **delimiter を変えるだけ**で空入力ガードではない。`find ... -print0 | xargs -0 cmd` も Linux では空入力時に `cmd` が呼ばれる
  - NG（Linux で空入力時に意図せず実行）: `find . -name '*.tmp' | xargs rm`
  - **両対応の推奨形 1**: `find -exec ... +` を使い xargs を経由しない（`find` は 0 件で utility を呼ばないため両 OS で安全）
    ```bash
    find . -name '*.tmp' -exec rm {} +
    ```
  - **両対応の推奨形 2**: 前段で空チェックする
    ```bash
    files=$(find . -name '*.tmp')
    [ -n "$files" ] && printf '%s\n' "$files" | xargs rm
    ```
  - 別解: GNU 専用環境では `xargs -r`、Brew で `findutils` (GNU coreutils 系) を入れて `gxargs -r` を使う
- **`-d` (delimiter)**: GNU 専用。両対応では `-0`（NUL 区切り）+ `find -print0` / `tr` でパイプ

### `ls`
- **色オプション**: GNU は `--color=auto`、BSD は `-G`
- 推奨: `eza` / `lsd` 等のクロスプラットフォームツールに置き換える

### `ps`
- **`-o tty=`**: 出力形式が macOS と Linux で違う（macOS は `ttys003`、Linux は `pts/3`）
- 解析する場合は OS 判定で分岐

---

## 2. シェル組み込みの差

### `read`
- **`-i` (default value)**: bash 4 以降のみ。macOS デフォルト bash は 3.x → 動かない
- **`-t` (timeout)**: 両対応だが、tty チェックの挙動差あり

### `[[ ... ]]` の `=~`
- 正規表現エンジンの差（BSD vs GNU）。両対応では POSIX `case ... esac` の方が安全

### `local` / `declare`
- macOS bash 3.x では `declare -A`（連想配列）が動かない。bash 4+ または zsh で書く

---

## 3. パスの違い

### Homebrew prefix
- macOS Intel: `/usr/local`
- macOS Apple Silicon: `/opt/homebrew`
- Linux: `/home/linuxbrew/.linuxbrew`
- 取得: `brew --prefix`（インストール済みなら）または `$(brew --prefix)/bin` を `PATH` に追加する

### システムパス
- `/usr/local/bin`: macOS Intel デフォルト、Linux にも存在
- `/opt/homebrew/bin`: macOS Apple Silicon
- 注意: `/usr/bin/local` は **実在しないタイポパターン**。`/usr/local/bin` の打ち間違いとして混入していないか確認

### ハードコードされたパスの検出
- `/Users/...` (macOS) や `/home/...` (Linux) を直書きしている箇所は基本的に NG
- `~`, `$HOME`, `$XDG_CONFIG_HOME` を使う

---

## 4. macOS 専用コマンド

WSL2 / Linux 側で代替手段を用意しているか確認:

| macOS 専用 | Linux 代替 |
|-----------|-----------|
| `pbcopy` / `pbpaste` | `xclip -selection clipboard`, `xsel`, `wl-copy` (Wayland), WSL は `clip.exe` |
| `osascript` | 代替なし（macOS 限定機能。OS 分岐で skip） |
| `defaults` | 代替なし（macOS の plist 操作。OS 分岐で skip） |
| `open` | `xdg-open` (Linux), `wslview` (WSL2) |
| `say` | `espeak` (Linux), 代替なしのケース多 |

---

## 5. Linux 専用コマンド

macOS 側で代替手段を用意しているか確認:

| Linux 専用 | macOS 代替 |
|-----------|-----------|
| `apt`, `apt-get`, `yum`, `dnf` | `brew` |
| `systemctl`, `service` | `launchctl`（用途が限定的） |
| `xdg-open` | `open` |
| `xdg-mime` | `duti` (Homebrew) |

---

## 6. WSL2 特有の処理

- **WSL2 検出**: `uname -r` の結果に `WSL2` が含まれるか、`/proc/version` を見る
  ```bash
  if grep -qi microsoft /proc/version 2>/dev/null; then
      # WSL 環境
  fi
  ```
- **`/mnt/c/` 系のパス**: Windows ファイルシステムへのアクセス。パフォーマンス低下に注意
- **クリップボード**: `clip.exe`（コピー）/ `powershell.exe Get-Clipboard`（ペースト）

---

## 7. Brewfile / セットアップスクリプトの対称性

### `if OS.mac?` / `if OS.linux?` ブロック
- 片方の OS で `brew` パッケージを追加したら、もう片方に **同等のものが必要か検討する**
- macOS 専用 GUI アプリ（`cask`）は Linux 側で対応するアプリを `brew install` できる場合がある
- Linux 側で apt 等を別途使うなら、`Brewfile` ではなく別のセットアップステップに移す

### CI / ローカルの両対応
- `setup.sh` の冒頭で `OS=$(uname -s)` を取得し、case 文で分岐するパターンが標準
- ステップ間で「macOS では成功、Linux では未テスト」のような片対応が無いか確認

---

## 8. zsh モジュール構成（dotfiles 想定）

### `zsh/os/darwin.zsh` / `zsh/os/linux.zsh` の対称性
- `darwin.zsh` で alias / function / env を追加したら、Linux 側に対応する記述が必要か検討
- Linux 側で取得できないコマンド（`pbcopy` 等）への alias は darwin 専用に隔離

### 共通モジュール内での OS 分岐
- 共通モジュール（例: `zsh/modules/git.zsh`）で OS 依存処理を書く場合、`[[ "$OSTYPE" == darwin* ]]` 等で確実に分岐する
- 片方の分岐だけ書いて他方が空になっていないかチェック

---

## 9. シェバン (`#!`)

- **`#!/bin/bash`**: macOS デフォルト bash は 3.x、Linux は 4+ → bash 4+ 機能は動かない
  - 推奨: bash 4+ に依存するなら Brewfile で `bash` を追加し `#!/usr/bin/env bash` で `$PATH` から拾う
- **`#!/bin/sh`**: Linux では多くが dash、macOS は bash 互換の sh → POSIX 範囲で書く
- **`#!/usr/bin/env bash`**: 推奨。`$PATH` 上の bash を使う

---

## 10. ファイルシステム差

- **大文字小文字**: macOS デフォルト APFS は **case-insensitive**、Linux ext4 は **case-sensitive** → ファイル名違いの import 等で破綻する
- **改行コード**: WSL2 で git の autocrlf が効くと CRLF になることがある。`.gitattributes` で制御
- **パーミッション**: macOS の execute bit が WSL2 経由で消えることがある

---

## 重要度の判定基準

| 重要度 | 判定 |
|--------|------|
| BLOCKER | 片方の OS でエラー終了する（実行不可能） |
| HIGH | 片方の OS で意図と違う動作をする（silent な誤動作） |
| MED | 警告は出るが動く、または OS 判定漏れの片対応 |
| LOW | 改善推奨（より移植性の高い書き方が存在） |
