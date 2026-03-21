use std::process::{Child, Command};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, PhysicalPosition, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// 用户主动退出标志
static SHOULD_QUIT: AtomicBool = AtomicBool::new(false);

const BACKEND_PORT: u16 = 8766;
const BACKEND_URL: &str = "http://127.0.0.1:8766";
const APP_URL: &str = "http://127.0.0.1:8766/app";
/// 桌宠页面（与主程序同时启动，也可托盘显示/隐藏）
const PET_URL: &str = "http://127.0.0.1:8766/pet";
const HEALTH_URL: &str = "http://127.0.0.1:8766/api/ping";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(120);
const HEALTH_POLL: Duration = Duration::from_millis(500);

// ── Python 后端管理 ─────────────────────────────────────────

struct PythonBackend {
    child: Mutex<Option<Child>>,
}

impl PythonBackend {
    fn new() -> Self {
        Self {
            child: Mutex::new(None),
        }
    }

    fn start(&self) -> Result<(), String> {
        let mut guard = self.child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            return Ok(());
        }
        if check_port_open(BACKEND_PORT) {
            return Ok(());
        }

        let python = find_python()
            .ok_or_else(|| "未找到 Python 3.10+".to_string())?;

        let work_dir = find_project_dir()
            .ok_or_else(|| "未找到项目目录（src/server/main.py），请设置 OPENCLAW_HOME 环境变量".to_string())?;

        eprintln!("[Tauri] Python: {}", python);
        eprintln!("[Tauri] Project: {}", work_dir.display());

        #[cfg(windows)]
        use std::os::windows::process::CommandExt;

        let mut cmd = Command::new(&python);
        cmd.args(["-m", "src.server.main"])
            .env("PYTHONPATH", ".")
            .env("OPENCLAW_DESKTOP", "1")
            .current_dir(&work_dir);

        #[cfg(windows)]
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW

        let child = cmd.spawn()
            .map_err(|e| format!("启动失败 ({}): {}", python, e))?;

        *guard = Some(child);
        Ok(())
    }

    fn stop(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                #[cfg(windows)]
                {
                    let _ = Command::new("taskkill")
                        .args(["/PID", &child.id().to_string(), "/T", "/F"])
                        .output();
                }
                let _ = child.kill();
                // Wait with timeout to avoid deadlock on exit
                let pid = child.id();
                std::thread::spawn(move || {
                    let _ = child.wait();
                });
                eprintln!("[Tauri] Sent kill to PID {}", pid);
            }
        }
    }

    fn is_running(&self) -> bool {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(ref mut child) = *guard {
                return child.try_wait().ok().flatten().is_none();
            }
        }
        false
    }
}

impl Drop for PythonBackend {
    fn drop(&mut self) {
        self.stop();
    }
}

fn find_python() -> Option<String> {
    let subs = &["python/python.exe", "embedded/python/python.exe"];

    // 1. EXE 所在目录（安装后最可靠的查找路径）
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            for sub in subs {
                let p = dir.join(sub);
                if p.exists() {
                    return Some(p.to_string_lossy().to_string());
                }
            }
        }
    }

    // 2. 当前工作目录（开发或便携模式）
    if let Ok(cwd) = std::env::current_dir() {
        for sub in subs {
            let p = cwd.join(sub);
            if p.exists() {
                return Some(p.to_string_lossy().to_string());
            }
        }
    }

    // 3. Inno Setup 默认安装目录
    if let Ok(appdata) = std::env::var("LOCALAPPDATA") {
        let inno_python = std::path::PathBuf::from(&appdata)
            .join("ShisanXiang")
            .join("python")
            .join("python.exe");
        if inno_python.exists() {
            return Some(inno_python.to_string_lossy().to_string());
        }
    }

    // 4. 环境变量指定
    if let Ok(p) = std::env::var("OPENCLAW_PYTHON") {
        if !p.is_empty() {
            return Some(p);
        }
    }

    // 5. 系统 Python（验证版本 >= 3.10）
    for name in &["python", "python3"] {
        if let Ok(output) = Command::new(name).arg("--version").output() {
            if output.status.success() {
                let ver = String::from_utf8_lossy(&output.stdout);
                if ver.contains("3.1") || ver.contains("3.2") {
                    return Some(name.to_string());
                }
            }
        }
    }
    None
}

/// 查找项目根目录（含 src/server/main.py 的目录）
fn find_project_dir() -> Option<std::path::PathBuf> {
    let marker = "src/server/main.py";

    let mut candidates: Vec<std::path::PathBuf> = Vec::new();

    // 1. EXE 所在目录（安装后最可靠）及其父级
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.to_path_buf());
            if let Some(parent) = dir.parent() {
                candidates.push(parent.to_path_buf());
            }
        }
    }

    // 2. 环境变量指定
    if let Ok(p) = std::env::var("OPENCLAW_HOME") {
        candidates.push(std::path::PathBuf::from(p));
    }

    // 3. 当前目录
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.clone());
        if let Some(parent) = cwd.parent() {
            candidates.push(parent.to_path_buf());
        }
    }

    // 4. Inno Setup 安装目录
    if let Ok(appdata) = std::env::var("LOCALAPPDATA") {
        candidates.push(std::path::PathBuf::from(&appdata).join("ShisanXiang"));
    }

    // 5. 常见开发路径
    for dev_path in &["D:/xlx2026/openclaw-voice", "C:/openclaw-voice"] {
        candidates.push(std::path::PathBuf::from(dev_path));
    }

    for dir in &candidates {
        if dir.join(marker).exists() {
            return Some(dir.clone());
        }
    }
    None
}

fn check_port_open(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &format!("127.0.0.1:{}", port).parse().unwrap(),
        Duration::from_millis(200),
    )
    .is_ok()
}

fn wait_for_backend() -> bool {
    let start = Instant::now();
    while start.elapsed() < HEALTH_TIMEOUT {
        if let Ok(resp) = ureq::get(HEALTH_URL).timeout(Duration::from_secs(2)).call() {
            if resp.status() == 200 {
                return true;
            }
        }
        std::thread::sleep(HEALTH_POLL);
    }
    false
}

// ── Tauri 命令 ─────────────────────────────────────────

#[tauri::command]
fn backend_status(state: tauri::State<PythonBackend>) -> serde_json::Value {
    let running = state.is_running() || check_port_open(BACKEND_PORT);
    serde_json::json!({
        "running": running,
        "port": BACKEND_PORT,
        "url": BACKEND_URL,
    })
}

#[tauri::command]
fn focus_main_window(app: tauri::AppHandle) -> Result<(), String> {
    if let Some(w) = app.get_webview_window("main") {
        w.show().map_err(|e| e.to_string())?;
        let _ = w.unminimize();
        w.set_focus().map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn restart_backend(state: tauri::State<PythonBackend>) -> Result<String, String> {
    state.stop();
    std::thread::sleep(Duration::from_secs(2));
    state.start()?;
    if wait_for_backend() {
        Ok("restarted".to_string())
    } else {
        Err("后端重启超时".to_string())
    }
}

// ── 主入口 ─────────────────────────────────────────────

/// 单实例互斥锁（Windows Named Mutex）
fn single_instance_lock() -> Option<()> {
    #[cfg(windows)]
    {
        use std::ptr;
        #[link(name = "kernel32")]
        extern "system" {
            fn CreateMutexW(attrs: *const u8, owner: i32, name: *const u16) -> *mut u8;
            fn GetLastError() -> u32;
        }
        let name: Vec<u16> = "ShisanXiang_SingleInstance\0".encode_utf16().collect();
        unsafe {
            let handle = CreateMutexW(ptr::null(), 1, name.as_ptr());
            if handle.is_null() || GetLastError() == 183 {
                // ERROR_ALREADY_EXISTS = 183
                return None;
            }
            // 不要 close handle — 让它在进程结束时自动释放
            std::mem::forget(handle);
        }
    }
    Some(())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // 单实例锁：防止重复启动
    let _mutex = match single_instance_lock() {
        Some(m) => m,
        None => {
            eprintln!("[Tauri] Another instance is already running");
            return;
        }
    };

    let backend = PythonBackend::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(backend)
        .setup(|app| {
            let state = app.state::<PythonBackend>();
            let (python_missing, project_missing) = match state.start() {
                Ok(_) => (false, false),
                Err(e) => {
                    eprintln!("[Tauri] Start error: {}", e);
                    (e.contains("未找到 Python"), e.contains("未找到项目"))
                }
            };

            // ── 系统托盘 ──────────────────────────────
            // 统一托盘菜单（与 Python launcher 一致）
            let title = MenuItem::with_id(app, "title", "🦞 十三香 AI 工作队", false, None::<&str>)?;
            let sep1 = PredefinedMenuItem::separator(app)?;
            let show = MenuItem::with_id(app, "show", "🖥️ 显示主窗口", true, None::<&str>)?;
            let browser = MenuItem::with_id(app, "browser", "🌐 浏览器打开", true, None::<&str>)?;
            let qr = MenuItem::with_id(app, "qr", "📱 手机扫码连接", true, None::<&str>)?;
            let chat = MenuItem::with_id(app, "chat", "💬 聊天界面", true, None::<&str>)?;
            let sep2 = PredefinedMenuItem::separator(app)?;
            let pet_show = MenuItem::with_id(app, "pet_show", "🐾 显示桌宠", true, None::<&str>)?;
            let pet_hide = MenuItem::with_id(app, "pet_hide", "🙈 隐藏桌宠", true, None::<&str>)?;
            let sep3 = PredefinedMenuItem::separator(app)?;
            let settings = MenuItem::with_id(app, "settings", "⚙️ 设置", true, None::<&str>)?;
            let admin = MenuItem::with_id(app, "admin", "📊 管理面板", true, None::<&str>)?;
            let restart = MenuItem::with_id(app, "restart", "🔄 重启服务", true, None::<&str>)?;
            let sep4 = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "❌ 退出", true, None::<&str>)?;
            let menu = Menu::with_items(
                app,
                &[&title, &sep1, &show, &browser, &qr, &chat, &sep2,
                  &pet_show, &pet_hide, &sep3, &settings, &admin, &restart, &sep4, &quit],
            )?;

            let _tray = TrayIconBuilder::new()
                .icon(app.default_window_icon().unwrap().clone())
                .tooltip("十三香小龙虾 AI")
                .menu(&menu)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.unminimize();
                            let _ = w.set_focus();
                        }
                    }
                    "restart" => {
                        let state = app.state::<PythonBackend>();
                        state.stop();
                        std::thread::sleep(Duration::from_secs(1));
                        let _ = state.start();
                    }
                    "browser" => {
                        let _ = open::that(APP_URL);
                    }
                    "qr" => {
                        let _ = open::that(format!("{}/qr", BACKEND_URL));
                    }
                    "chat" => {
                        let _ = open::that(format!("{}/chat", BACKEND_URL));
                    }
                    "settings" => {
                        let _ = open::that(format!("{}/setup", BACKEND_URL));
                    }
                    "admin" => {
                        let _ = open::that(format!("{}/admin", BACKEND_URL));
                    }
                    "pet_show" => {
                        if let Some(w) = app.get_webview_window("pet") {
                            let _ = w.show();
                            let _ = w.unminimize();
                            let _ = w.set_focus();
                        }
                    }
                    "pet_hide" => {
                        if let Some(w) = app.get_webview_window("pet") {
                            let _ = w.hide();
                        }
                    }
                    "quit" => {
                        SHOULD_QUIT.store(true, Ordering::SeqCst);
                        let state = app.state::<PythonBackend>();
                        state.stop();
                        let handle = app.clone();
                        std::thread::spawn(move || {
                            std::thread::sleep(Duration::from_millis(300));
                            handle.exit(0);
                        });
                        // Fallback: force exit if app.exit doesn't work within 3s
                        let _ = std::thread::spawn(|| {
                            std::thread::sleep(Duration::from_secs(3));
                            std::process::exit(0);
                        });
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    // 左键单击显示窗口
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        let app = tray.app_handle();
                        if let Some(w) = app.get_webview_window("main") {
                            let _ = w.show();
                            let _ = w.unminimize();
                            let _ = w.set_focus();
                        }
                    }
                })
                .build(app)?;

            // ── 启动画面（splash 窗口）──
            let splash_html = r#"data:text/html,<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{margin:0;padding:0}body{background:%230b0b16;color:%23e8e8f0;font-family:-apple-system,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;user-select:none}.logo{font-size:48px;margin-bottom:16px}h1{font-size:20px;font-weight:600;margin-bottom:16px;color:%23c8c8d8}.pbar{width:200px;height:4px;background:%231a1a2e;border-radius:2px;overflow:hidden;margin-bottom:12px}.pfill{height:100%25;width:5%25;background:linear-gradient(90deg,%237c6aef,%23e94560);border-radius:2px;transition:width .5s}.hint{font-size:12px;color:%23888;margin-bottom:8px}.detail{font-size:11px;color:%23555;display:flex;gap:8px;flex-wrap:wrap;justify-content:center}</style></head>
<body><div class="logo">🦞</div><h1>十三香小龙虾 AI</h1><div class="pbar"><div class="pfill" id="bar"></div></div><div class="hint" id="msg">正在启动...</div><div class="detail" id="det"></div>
<script>var icons={pending:'⏳',loading:'⏳',ready:'✅',error:'❌'},names={stt:'语音识别',tts:'语音合成',backend:'AI引擎',workflow:'工作流'};function poll(){fetch('http://127.0.0.1:8766/api/startup-status').then(function(r){return r.json()}).then(function(d){document.getElementById('msg').textContent=d.message||'加载中...';var c=d.components||{},done=0,n=0,h='';for(var k in c){n++;if(c[k]==='ready')done++;h+='<span>'+(icons[c[k]]||'⏳')+' '+(names[k]||k)+'</span>'}document.getElementById('det').innerHTML=h;document.getElementById('bar').style.width=Math.min(95,5+done/Math.max(n,1)*90)+'%25'}).catch(function(){});setTimeout(poll,1200)}poll()</script></body></html>"#;

            if !python_missing && !project_missing {
                let _ = WebviewWindowBuilder::new(
                    app,
                    "splash",
                    WebviewUrl::External(splash_html.parse().unwrap()),
                )
                .title("十三香小龙虾 AI")
                .inner_size(400.0, 300.0)
                .center()
                .decorations(false)
                .resizable(false)
                .build()?;
            }

            // ── 后台等待后端就绪，然后关闭 splash 打开 main ──
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                if python_missing || project_missing {
                    let msg = if python_missing {
                        "未找到 Python 3.10%2B，请安装 Python 后重启"
                    } else {
                        "未找到项目文件，请设置 OPENCLAW_HOME 环境变量"
                    };
                    let error_html = format!(
                        "data:text/html,<!DOCTYPE html><html><head><meta charset=utf-8><style>*{{margin:0}}body{{background:%230b0b16;color:%23e8e8f0;font-family:sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;padding:40px;text-align:center}}.icon{{font-size:48px;margin-bottom:16px}}h1{{font-size:20px;margin-bottom:12px}}p{{color:%23888;font-size:14px}}</style></head><body><div class=icon>⚠️</div><h1>启动失败</h1><p>{}</p></body></html>",
                        msg
                    );
                    let _ = WebviewWindowBuilder::new(
                        &app_handle, "main",
                        WebviewUrl::External(error_html.parse().unwrap()),
                    ).title("十三香小龙虾 AI").inner_size(500.0, 400.0).center().build();
                    return;
                }

                let ready = wait_for_backend();

                if let Some(w) = app_handle.get_webview_window("splash") {
                    let _ = w.close();
                }

                let target_url = if ready {
                    APP_URL.to_string()
                } else {
                    eprintln!("[Tauri] Backend not ready after timeout, showing error page");
                    format!("{}/error", BACKEND_URL)
                };
                let title = if ready { "十三香小龙虾 AI" } else { "十三香小龙虾 AI - 启动超时" };

                let _ = WebviewWindowBuilder::new(
                    &app_handle, "main",
                    WebviewUrl::External(target_url.parse().unwrap()),
                )
                .title(title)
                .inner_size(1280.0, 800.0)
                .min_inner_size(800.0, 600.0)
                .center()
                .build();

                // 桌宠：与主窗口一同出现（后端就绪且非错误页时）
                if ready {
                    match WebviewWindowBuilder::new(
                        &app_handle,
                        "pet",
                        WebviewUrl::External(PET_URL.parse().unwrap()),
                    )
                    .title("桌宠")
                    .inner_size(160.0, 220.0)
                    .min_inner_size(130.0, 180.0)
                    .decorations(false)
                    .transparent(true)
                    .always_on_top(true)
                    .skip_taskbar(true)
                    .resizable(true)
                    .build()
                    {
                        Ok(pet) => {
                            if let Ok(Some(monitor)) = app_handle.primary_monitor() {
                                let pos = monitor.position();
                                let size = monitor.size();
                                let margin = 16i32;
                                let pw = 160i32;
                                let ph = 220i32;
                                let x = pos.x + size.width as i32 - pw - margin;
                                let y = pos.y + size.height as i32 - ph - margin;
                                let _ = pet.set_position(PhysicalPosition::new(x, y));
                            }
                            let _ = pet.show();
                        }
                        Err(e) => eprintln!("[Tauri] pet window: {}", e),
                    }
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            backend_status,
            restart_backend,
            focus_main_window
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| match event {
            // 关闭窗口 → 隐藏到托盘（不退出）
            RunEvent::WindowEvent {
                label,
                event: tauri::WindowEvent::CloseRequested { api, .. },
                ..
            } if label == "main" => {
                api.prevent_close();
                if let Some(w) = app_handle.get_webview_window("main") {
                    let _ = w.hide();
                }
            }
            RunEvent::WindowEvent {
                label,
                event: tauri::WindowEvent::CloseRequested { api, .. },
                ..
            } if label == "pet" => {
                api.prevent_close();
                if let Some(w) = app_handle.get_webview_window("pet") {
                    let _ = w.hide();
                }
            }
            RunEvent::ExitRequested { ref api, .. } => {
                if !SHOULD_QUIT.load(Ordering::SeqCst) {
                    api.prevent_exit();
                }
                // Backend cleanup already handled in the quit menu handler;
                // Drop impl also calls stop() as a safety net.
            }
            _ => {}
        });
}
