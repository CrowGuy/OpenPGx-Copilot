# PostgreSQL on Docker Playbook

適用對象：第一次用 Docker 架 PostgreSQL 的團隊成員。
適用範圍：GWAS Data Platform 的 Curated Layer 資料庫（ADR-0004、ADR-0006、ADR-0008）。

> 本文的設定檔是**教學範例**。實際設定由 #4（本機開發）與 #11（正式環境）實作進 repo；兩者有差異時以 repo 為準，並回頭更新本文。

---

## 1. 先懂四個概念

| 概念 | 一句話 | 在本專案的角色 |
|---|---|---|
| **Image** | 唯讀的軟體安裝包 | `postgres:18`：官方 PostgreSQL 18 |
| **Container** | 從 image 跑起來的一個執行中實體，可以隨時刪掉重建 | 跑資料庫的那個 process |
| **Volume** | Docker 管理的持久化儲存，**container 刪掉資料還在** | 存放資料庫檔案，這是唯一不能丟的東西 |
| **Compose** | 用一個 YAML 檔描述「要跑哪些 container、掛哪些 volume、開哪些 port」 | 讓部署可以重現、可以 code review |

最重要的心智模型：**container 是可拋棄的，volume 才是資料**。升級、改設定、重開機，都只是「刪掉 container、用新設定重建」，資料留在 volume 裡。

---

## 2. 在伺服器上安裝 Docker（Ubuntu）

用 Docker 官方的 apt repository 安裝，不要用 Ubuntu 內建的 `docker.io` 套件（版本較舊）：

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
  https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
  | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

驗證：

```bash
sudo docker run --rm hello-world
docker compose version
```

讓自己不用每次打 `sudo`（重新登入後生效）：

```bash
sudo usermod -aG docker "$USER"
```

> ⚠️ `docker` 群組等同 root 權限，只加給需要維運資料庫的人。

---

## 3. 目錄結構

伺服器上統一放在 `/srv/openpgx/`：

```
/srv/openpgx/
├── compose.yaml          # 服務定義
├── secrets/              # 密碼檔，權限 600，絕不進 git
│   ├── postgres_superuser
│   ├── etl_writer
│   └── analyst_ro
├── initdb/               # 第一次建立資料庫時執行的腳本
│   └── 01-roles.sh
├── conf/
│   └── pg_hba.conf       # 誰可以從哪裡、用什麼方式連線
├── tls/                  # TLS 憑證與私鑰
│   ├── server.crt
│   └── server.key
├── raw/                  # RawSnapshot 正式存放處（ADR-0008）
└── backups/              # pg_dump 備份
```

```bash
sudo mkdir -p /srv/openpgx/{secrets,initdb,conf,tls,raw,backups}
sudo chown -R "$USER": /srv/openpgx
chmod 700 /srv/openpgx/secrets
```

---

## 4. 產生密碼

每個角色一個隨機密碼，各存一個檔：

```bash
cd /srv/openpgx/secrets
for r in postgres_superuser etl_writer analyst_ro; do
  openssl rand -base64 32 | tr -d '\n' > "$r"
done
chmod 600 *
```

| 角色 | 誰用 | 權限 |
|---|---|---|
| `postgres` | 只有維運者，處理升級或緊急狀況 | superuser |
| `etl_writer` | 只有 loader | 建立 Release schema、寫入 |
| `analyst_ro` | 團隊成員 | 只能讀 `gwas`、`meta` 與 Release schema |

密碼透過 Docker secrets 掛進 container，**不要寫在 `compose.yaml` 或環境變數裡**，因為那些會出現在 `docker inspect` 的輸出和 shell history 中。

---

## 5. 初始化角色

`initdb/` 裡的腳本**只在 volume 是空的時候執行一次**（第一次啟動）。之後再改這些腳本不會生效，要改角色就直接下 SQL。

`/srv/openpgx/initdb/01-roles.sh`：

```bash
#!/bin/bash
set -euo pipefail
etl_pw=$(cat /run/secrets/etl_writer)
ro_pw=$(cat /run/secrets/analyst_ro)
# 密碼由第 4 節的 openssl rand -base64 產生，不含單引號，可以直接放進 '...'。
# 不使用 psql 的 -v 變數替換（:'var'）：實測時沒有被替換，密碼因此沒有設定成功。
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE etl_writer LOGIN PASSWORD '${etl_pw}';
CREATE ROLE analyst_ro LOGIN PASSWORD '${ro_pw}';
REVOKE ALL ON DATABASE openpgx FROM PUBLIC;
GRANT CONNECT ON DATABASE openpgx TO etl_writer, analyst_ro;
GRANT CREATE ON DATABASE openpgx TO etl_writer;   -- 讓 loader 能建立 schema
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
```

```bash
chmod 755 /srv/openpgx/initdb/01-roles.sh
```

`meta`、`gwas` 這些 schema 與讀取授權由 repo 中的 migration 建立（#4、#10），不放在這裡。

### 重設角色密碼

初始化腳本只會執行一次。之後要修改密碼（或發現初始化時密碼沒有設定成功），在 `/srv/openpgx` 目錄下執行：

```bash
pw=$(sudo cat /srv/openpgx/secrets/analyst_ro)          # 換成要重設的角色：etl_writer、analyst_ro
printf "ALTER ROLE analyst_ro PASSWORD '%s';\n" "$pw" \
  | sudo docker compose exec -T -u postgres db psql -d openpgx -v ON_ERROR_STOP=1
unset pw
```

- 看到 `ALTER ROLE` 就代表成功。
- `printf` 是 shell 內建指令，密碼不會出現在 `ps` 的行程列表中，而是透過管線送給 psql。
- 輸入來自管線，所以 `exec` 一定要加 `-T`；沒有加會出現 `the input device is not a TTY`。
- superuser `postgres` 在伺服器上用 peer 登入（第 7 節），平常不需要密碼。如果要重設它的密碼，把角色換成 `postgres`、密碼檔換成 `secrets/postgres_superuser`。

---

## 6. TLS 憑證

團隊內網使用時，可以用自簽憑證。如果組織有內部 CA，就改用內部 CA 簽發的憑證，這樣 client 才能做完整驗證。

```bash
cd /srv/openpgx/tls
openssl req -new -x509 -days 825 -nodes \
  -subj "/CN=openpgx-db.internal" \
  -addext "subjectAltName=DNS:openpgx-db.internal,IP:10.0.201.134" \
  -keyout server.key -out server.crt
# container 內的 postgres 使用者 uid 是 999；私鑰必須屬於它且權限是 600
sudo chown 999:999 server.key server.crt
sudo chmod 600 server.key
```

把 `10.0.201.134` 和 `openpgx-db.internal` 換成伺服器實際的內網 IP 與主機名稱。

---

## 7. 連線規則 `pg_hba.conf`

`pg_hba.conf` 由上往下比對，第一條符合的規則生效。

`/srv/openpgx/conf/pg_hba.conf`：

```
# TYPE    DATABASE  USER        ADDRESS          METHOD
local     all       postgres                     peer
local     all       all                          scram-sha-256
hostssl   openpgx   all         10.0.201.0/24   scram-sha-256
hostssl   openpgx   etl_writer  172.30.0.1/32    scram-sha-256
host      all       all         0.0.0.0/0        reject
host      all       all         ::/0             reject
```

意思是：

- **第 2–3 行（`local`）**：只適用於 container 內部的 Unix socket，也就是 `docker compose exec ... psql`。從 host 透過網路連線**不算** `local`。
  - 第 2 行用 `peer`：container 內的作業系統使用者 `postgres` 可以不輸入密碼，以 superuser `postgres` 登入。所以維運指令一律寫成 `docker compose exec -u postgres db ...`。不加 `-u postgres` 時，指令會以 container 內的 `root` 執行，名稱不符，peer 會拒絕。
  - 這樣並沒有放寬權限：能執行 `docker compose exec` 的人本來就等同伺服器的 root，可以直接讀密碼檔。這一行讓維運指令和 cron 備份不需要輸入密碼。
  - 第 3 行：其他角色從 container 內部連線時，仍然要輸入密碼。
- **第 4 行**：團隊成員只能從**內網網段**、用 **TLS** 加上 **scram-sha-256 密碼**連線。`10.0.201.0/24` 是團隊伺服器（`10.0.201.134`）所在的網段；用 `ip -4 addr show` 確認斜線後的數字。團隊成員如果還在其他網段（例如透過 VPN），每個網段各加一行 `hostssl`，都要放在 `reject` 之前。見第 11 節。
- **第 5 行**：給在伺服器本機執行的 loader 使用。只開放 `etl_writer` 一個角色，而且只開放 Docker 網路閘道這一個 IP。原因見第 11 節。
- **最後兩行**：其他 IPv4 與 IPv6 連線一律拒絕。`host` 同時涵蓋有 TLS 和沒有 TLS 的連線，所以不需要另外寫 `hostnossl`。
- 規則**由上往下比對**，新增的允許規則一定要放在 `reject` 之前。

CIDR 寫法速查：`/32` 是單一 IP；`/24` 是最後一段可以變動（256 個位址，通常是一個辦公室網段）；`/16` 是後兩段可以變動（65,536 個位址，通常太寬）。原則是開到剛好夠用的最小範圍。

---

## 8. `compose.yaml`

`/srv/openpgx/compose.yaml`：

```yaml
services:
  db:
    image: postgres:18            # 固定 major 版本；不要用 latest
    restart: unless-stopped
    environment:
      POSTGRES_DB: openpgx
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_superuser
    secrets: [postgres_superuser, etl_writer, analyst_ro]
    command:
      - postgres
      - -c
      - ssl=on
      - -c
      - ssl_cert_file=/etc/postgresql/tls/server.crt
      - -c
      - ssl_key_file=/etc/postgresql/tls/server.key
      - -c
      - hba_file=/etc/postgresql/conf/pg_hba.conf
      - -c
      - password_encryption=scram-sha-256
    volumes:
      - pgdata:/var/lib/postgresql   # PostgreSQL 18 起的官方 image 掛在這一層
      - ./initdb:/docker-entrypoint-initdb.d:ro
      - ./conf:/etc/postgresql/conf:ro   # 掛整個目錄，不要只掛單一檔案（見下方說明）
      - ./tls:/etc/postgresql/tls:ro
    ports:
      - "10.0.201.134:5432:5432"   # 只綁內網 IP，絕不寫成 "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d openpgx"]
      interval: 10s
      retries: 5

volumes:
  pgdata:

networks:
  default:
    ipam:
      config:
        - subnet: 172.30.0.0/24   # 固定網段，pg_hba.conf 的 etl_writer 規則依賴它（第 11 節）
          gateway: 172.30.0.1

secrets:
  postgres_superuser: { file: ./secrets/postgres_superuser }
  etl_writer:         { file: ./secrets/etl_writer }
  analyst_ro:         { file: ./secrets/analyst_ro }
```

> ⚠️ **Docker 會繞過 ufw 防火牆。** `ports: "5432:5432"` 等於把資料庫開放給所有網路介面，即使 ufw 設定了拒絕也一樣。所以一定要在 `ports` 裡寫明內網 IP。

> ⚠️ **設定檔要掛「目錄」，不要掛「單一檔案」。** Docker 掛載單一檔案時，綁定的是**那個檔案本身**，而不是那個路徑。`vim`、`nano`、`sed -i` 這類編輯器存檔時，通常是寫出一個新檔案再取代舊的，於是主機上看到新內容，container 裡卻還是舊的，不論 reload 幾次都不會生效。掛整個 `conf/` 目錄，container 每次都會依路徑讀到最新的檔案。如果之前是用單一檔案的方式掛載，改成目錄後要執行一次 `docker compose up -d --force-recreate db` 才會生效。

> ⚠️ **`networks` 那一段要先確認網段沒有衝突。** 執行 `ip route | grep 172.30`，沒有任何輸出才能使用。有輸出就改用其他網段（例如 `172.31.0.0/24`），並同步修改 `pg_hba.conf`。網段衝突會讓伺服器連不到公司網路裡同一個網段的機器。

---

## 9. 啟動與檢查

```bash
cd /srv/openpgx
docker compose up -d          # 背景啟動
docker compose ps             # STATUS 應該在幾秒後變成 healthy
docker compose logs -f db     # 看啟動訊息，Ctrl-C 離開
```

第一次啟動時，log 裡應該看到 `running /docker-entrypoint-initdb.d/01-roles.sh`。

在伺服器上用 superuser 檢查（`-u postgres` 走第 7 節的 peer 規則，不需要密碼）：

```bash
docker compose exec -u postgres db psql -d openpgx -c '\du'   # 列出角色
docker compose exec -u postgres db psql -d openpgx -c 'SHOW ssl;'
```

---

## 10. 團隊成員怎麼連

### 10.1 先在自己的電腦安裝 psql

只要連資料庫的話，**只裝 client，不需要安裝 PostgreSQL server**。如果執行 `psql` 時看到下面這個訊息，代表只裝了轉介程式 `pg_wrapper`，沒有真正的 `psql`：

```
Error: You must install at least one postgresql-client-<version> package
```

**方法 A：Ubuntu 內建套件（最快）**

```bash
sudo apt-get update
sudo apt-get install -y postgresql-client
psql --version
```

版本會比伺服器的 18 舊（例如 Ubuntu 24.04 是 16）。一般查詢都能正常使用，但部分 `\d` 系列指令可能顯示不完整。

**方法 B：和伺服器同版本的 client 18（建議）**

```bash
sudo apt-get install -y postgresql-common
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh    # 加入 PostgreSQL 官方套件庫，依提示按 Enter
sudo apt-get install -y postgresql-client-18
psql --version                                                  # 應該顯示 psql (PostgreSQL) 18.x
```

### 10.2 連線

從內網的另一台機器連線：

```bash
psql "host=10.0.201.134 port=5432 dbname=openpgx user=analyst_ro sslmode=require"
```

- **DBeaver**：新增 PostgreSQL 連線，在 SSL 分頁勾選「Use SSL」，SSL mode 選 `require`。
- **Python**：`psycopg.connect("host=... dbname=openpgx user=analyst_ro sslmode=require")`。
- 如果憑證是內部 CA 簽發的，改用 `sslmode=verify-full sslrootcert=ca.crt`，可以防止連到冒充的伺服器。

驗證安全設定確實生效（這兩個指令**都應該失敗**）：

```bash
psql "host=10.0.201.134 dbname=openpgx user=analyst_ro sslmode=disable"         # 沒有 TLS → 被拒絕
psql "host=10.0.201.134 dbname=openpgx user=analyst_ro sslmode=require" \
  -c 'CREATE TABLE t(x int)'                                                     # 唯讀 → 權限錯誤
```

---

## 11. 確認來源 IP，以及「伺服器自己連自己」的陷阱

### 11.1 用 log 確認 PostgreSQL 看到的來源 IP

`pg_hba.conf` 比對的是 **PostgreSQL 實際看到的來源 IP**，而這個 IP 不一定是你以為的那個。最可靠的確認方法，是讓 PostgreSQL 自己告訴你：

```bash
# 1) 從要開放的那台機器連線一次（第一次被拒絕沒關係）
psql "host=10.0.201.134 dbname=openpgx user=analyst_ro sslmode=require" -c 'select 1'

# 2) 在伺服器上查看 PostgreSQL 記錄的來源 IP
docker compose logs db | grep -E "no pg_hba.conf entry|pg_hba.conf rejects" | tail -1
# 例如：pg_hba.conf rejects connection for host "10.0.201.129", user "analyst_ro", database "openpgx", SSL encryption
```

被拒絕時會出現兩種訊息之一：

| 訊息 | 意思 |
|---|---|
| `pg_hba.conf rejects connection for host ...` | 比對到明確的 `reject` 規則。第 7 節的設定最後有 `reject` 規則，所以**通常看到的是這一種** |
| `no pg_hba.conf entry for host ...` | 沒有任何規則符合（`pg_hba.conf` 裡沒有 `reject` 規則時才會出現） |

`host "..."` 裡的位址，就是要寫進 `pg_hba.conf` 的來源。從 client 端連線時，`psql` 的錯誤訊息裡也會直接顯示同樣的內容，不一定要到伺服器上查 log。每位團隊成員各試一次，就能知道需要開放哪些網段。

連線**成功之後**，也可以從 PostgreSQL 內部確認來源 IP 與 TLS 狀態：

```sql
SELECT inet_client_addr() AS seen_as, ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid();
```

改完 `pg_hba.conf` 之後，一定要確認新規則有沒有寫錯。**寫錯的規則不會讓資料庫停止運作，PostgreSQL 會繼續沿用舊規則**，所以很容易以為已經改好了：

```bash
docker compose exec -u postgres db pg_ctl reload
docker compose exec -u postgres db psql -c \
  'SELECT line_number, type, user_name, address, auth_method, error FROM pg_hba_file_rules;'
# error 欄位有值 → 那一行寫錯了
```

### 11.2 陷阱：伺服器自己連自己時，來源 IP 不是 10.0.201.134

ETL 在伺服器上執行，所以 loader 會從**伺服器本機**連資料庫。這時 PostgreSQL 看到的來源 IP，**通常是 Docker 網路的閘道**（例如 `172.30.0.1`），而不是伺服器的內網 IP。原因如下：

PostgreSQL 跑在 container 裡，container 有自己的私有網路：

```
伺服器（host）
├── 對外網卡：10.0.201.134
└── Docker 網路：172.30.0.0/24
     ├── 閘道（host 那一端）：172.30.0.1
     └── db container：172.30.0.2   ← PostgreSQL 實際在這裡監聽
```

`ports: "10.0.201.134:5432:5432"` 的作用是「送到 10.0.201.134:5432 的連線，轉送給 172.30.0.2:5432」。但外部連線和本機連線的轉送方式不同：

| 從哪裡連線 | Docker 怎麼轉送 | PostgreSQL 看到的來源 |
|---|---|---|
| 其他機器（例如 10.0.201.129） | iptables 只改封包的**目的地**，來源不變 | `10.0.201.129` ✅ 符合團隊網段規則 |
| 伺服器本機（loader） | 由 **docker-proxy** 程式接手，再**用它自己的身分**從閘道發起新連線 | `172.30.0.1` ❌ 不在團隊網段內 → 被 `reject` |

這就是 `pg_hba.conf` 第 5 行存在的原因。另外：
- 改連 `127.0.0.1` 也沒用，因為 `ports` 只綁了 `10.0.201.134`。
- `local` 規則也不適用，它只管 container 內部的 Unix socket。

說「通常」，是因為實際看到的 IP 取決於 Docker 的設定。例如管理者把 `/etc/docker/daemon.json` 設成 `"userland-proxy": false`，就不會經過 docker-proxy，來源可能變成閘道或 host 的 IP。**不要猜，用 11.1 的方法確認。**

### 11.3 設定步驟

1. **固定 Docker 網段。** `compose.yaml` 的 `networks` 段落把網段固定在 `172.30.0.0/24`（第 8 節）。如果不固定，Docker 重建網路時可能分配到別的網段，`pg_hba.conf` 寫死的 IP 就會失效。
   - 修改 `networks` 之後，要重建 container 才會生效：
     ```bash
     docker compose down     # 只刪 container 和網路，volume 保留；絕不加 -v
     docker compose up -d
     ```
2. **確認 Docker 認定的閘道：**
   ```bash
   docker network ls    # 找到這個專案的網路，名稱通常是 <目錄名>_default，例如 openpgx_default
   docker network inspect openpgx_default \
     --format '{{range .IPAM.Config}}subnet={{.Subnet}} gateway={{.Gateway}}{{end}}'
   # 預期：subnet=172.30.0.0/24 gateway=172.30.0.1
   ```
3. **確認 PostgreSQL 實際看到的 IP。** 在伺服器上用 `etl_writer` 連線一次，再照 11.1 查看 log。這個 IP 應該和步驟 2 的閘道一致；**不一致時，以 log 為準**。
4. **把這個 IP 寫進 `pg_hba.conf` 第 5 行**，用 `/32`，只開放給 `etl_writer`。接著執行 `pg_ctl reload`，並檢查 `pg_hba_file_rules`。
5. **驗證：**
   ```bash
   # etl_writer 從本機連線 → 應該成功；seen_as = 172.30.0.1，ssl = t
   psql "host=10.0.201.134 dbname=openpgx user=etl_writer sslmode=require" -c \
     'SELECT inet_client_addr() AS seen_as, ssl FROM pg_stat_ssl WHERE pid = pg_backend_pid();'

   # analyst_ro 從本機連線 → 應該被拒絕（第 5 行只開放 etl_writer）
   psql "host=10.0.201.134 dbname=openpgx user=analyst_ro sslmode=require" -c 'select 1'
   ```

> 為什麼只開放給 `etl_writer`、而且用 `/32`：閘道 IP 代表「伺服器本機上的任何 process」，範圍不應該開得比需要的更大。

---

## 12. 備份與還原

依 ADR-0008：

- **只備份 `meta` schema**（未來加上 Copilot 的 Rule Evidence schema）。
- Release schema 不備份，可以從 RawSnapshot 加上 CurationContract 重建。

### 每天備份

`/srv/openpgx/backup-meta.sh`：

```bash
#!/bin/bash
set -euo pipefail
cd /srv/openpgx
ts=$(date +%Y%m%d-%H%M%S)
out="backups/meta-$ts.dump"
tmp="$out.partial"
trap 'rm -f "$tmp"' EXIT
# 先寫到暫存檔，成功才改名；失敗時不會留下一個看起來正常、其實是空的 .dump
docker compose exec -T -u postgres db pg_dump -d openpgx -n meta -Fc > "$tmp"
test -s "$tmp"                     # 檔案是空的 → 視為失敗
mv "$tmp" "$out"
echo "$(date -Is) OK $out $(stat -c %s "$out") bytes"
find backups -name 'meta-*.dump' -mtime +30 -delete   # 保留 30 天
```

**設定完成後，先手動執行一次，確認真的有產生備份檔：**

```bash
chmod 700 /srv/openpgx/backup-meta.sh
sudo /srv/openpgx/backup-meta.sh
ls -lh /srv/openpgx/backups/       # 應該有一個大小不是 0 的 meta-*.dump
```

確認可以正常執行之後，才加進 cron。cron 執行時要有 Docker 權限，所以用 root 的 crontab：

```bash
sudo crontab -e
# 加入這一行：每天 03:15 執行
15 3 * * * /srv/openpgx/backup-meta.sh >> /srv/openpgx/backups/backup.log 2>&1
```

腳本失敗時只會寫進 `backup.log`，**不會主動通知任何人**。最少要定期確認一次：

```bash
tail -5 /srv/openpgx/backups/backup.log     # 最後一行應該是近期的 OK
ls -lt /srv/openpgx/backups/ | head -3      # 最新的備份應該是今天或昨天
```

> 備份檔放在同一台伺服器上，只能防止誤刪資料，不能防止硬碟損壞。要把 `backups/` 和 `raw/` 同步到第二個儲存位置，這件事在 ADR-0008 還沒決定。

### 還原（先在測試環境演練）

```bash
docker compose exec -T -u postgres db pg_restore -d openpgx --clean --if-exists \
  < backups/meta-YYYYMMDD-HHMMSS.dump
```

**還原從來沒有演練過的備份，等於沒有備份。** 每次改了 `meta` 的結構之後，至少演練一次還原。

---

## 13. 日常操作

| 目的 | 指令 |
|---|---|
| 停止，資料保留 | `docker compose stop` |
| 改了 `compose.yaml` 之後套用 | `docker compose up -d` |
| 改了 `pg_hba.conf` 之後重新載入 | `docker compose exec -u postgres db pg_ctl reload` |
| 看資源用量 | `docker stats` |
| 套用同一個 major 版本的安全更新（例如 18.1 → 18.2） | `docker compose pull && docker compose up -d` |

**Major 版本升級**（例如 18 → 19）**不能只改 image tag**，因為資料檔格式不相容。正確做法：用 `pg_dumpall` 匯出 → 用新版本建立新的 volume → 匯入。對本專案來說更簡單的做法是：備份 `meta` → 用新版本建一個空的資料庫 → 還原 `meta` → 從 RawSnapshot 重新 load 需要的 Release。

> ⚠️ `docker compose down -v` 會**連 volume 一起刪除**，也就是刪掉整個資料庫。除非確定要從頭重建，否則不要加 `-v`。

---

## 14. 本機開發

開發者在自己的電腦上，可以用簡化版的設定：不需要 TLS，密碼寫在本機檔案，port 只綁 `127.0.0.1`。實際的開發用 Compose 設定與測試資料庫由 #4 放進 repo，照該 ticket 的 README 操作即可。

---

## 15. 疑難排解

| 症狀 | 常見原因 |
|---|---|
| `docker compose ps` 一直不是 healthy | 看 `docker compose logs db`。最常見的是 TLS 私鑰權限不對（必須是 uid 999、權限 600） |
| `pg_hba.conf rejects connection for host "x.x.x.x"` | client 的 IP 不在任何 `hostssl` 允許的網段，所以落到最後的 `reject` 規則。把 `host "..."` 裡的 IP 所在網段加進第 7 節的第 4 行（第 11.1 節） |
| `no pg_hba.conf entry for host` | client 的 IP 不在 `hostssl` 那一行的網段，或者沒有用 `sslmode=require`。log 裡 `host "..."` 就是 PostgreSQL 看到的 IP（第 11.1 節） |
| loader 在伺服器上連不進去，但其他機器可以 | 伺服器自己連自己時，來源是 Docker 閘道（例如 `172.30.0.1`），不是 `10.0.201.134`（第 11.2 節） |
| `You must install at least one postgresql-client-<version> package` | client 端只裝了 `pg_wrapper`，沒有真正的 `psql`。照第 10.1 節安裝 client |
| 角色登入時 `password authentication failed`，但密碼確定是密碼檔的內容 | 初始化時密碼可能沒有設定成功。照第 5 節「重設角色密碼」重設 |
| `the input device is not a TTY` | 用 heredoc 或管線把輸入送給 `docker compose exec` 時，沒有加 `-T` |
| `syntax error at or near ":"`，SQL 裡出現 `:'pw'` 這類字樣 | psql 的 `-v` 變數沒有被替換。改用第 5 節「重設角色密碼」的 `printf` 寫法 |
| `docker compose exec` 進去執行 psql 時被問密碼 | 沒有加 `-u postgres`；或第 7 節的 `local all postgres peer` 沒有生效。先用 `docker compose exec db cat /etc/postgresql/conf/pg_hba.conf` 確認 container 看到的內容 |
| 改了 `pg_hba.conf` 卻沒有效果 | 用 `docker compose exec db cat /etc/postgresql/conf/pg_hba.conf` 確認 container 看到的是新內容；如果還是舊內容，表示用的是單一檔案掛載（第 8 節），執行 `docker compose up -d --force-recreate db`。內容正確的話，新規則寫錯時 PostgreSQL 會沿用舊規則；查看 `pg_hba_file_rules` 的 `error` 欄位，並確認新規則放在 `reject` 之前 |
| 改了 `initdb/` 卻沒有效果 | 這些腳本只在 volume 是空的時候執行；要改角色，直接下 SQL |
| `password authentication failed` | 密碼檔結尾多了換行，產生密碼時要用 `tr -d '\n'` |
| 內網其他機器連不到 | `ports` 綁的 IP 不對；或者主機防火牆、路由沒有開放 5432 |
