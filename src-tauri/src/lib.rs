use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::menu::{Menu, MenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const BACKEND_PORT: u16 = 8766;
const BACKEND_URL: &str = "http://localhost:8766";
const APP_URL: &str = "http://localhost:8766/app";
const HEALTH_URL: &str = "http://localhost:8766/api/health";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
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

        let child = Command::new(&python)
            .args(["-m", "src.server.main"])
            .env("PYTHONPATH", ".")
            .current_dir(&work_dir)
            .spawn()
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
                        .args(["/PID", &child.id().to_string(), "/T"])
                        .output();
                }
                let _ = child.kill();
                let _ = child.wait();
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
    // 1. 同目录内嵌 Python（开发或便携模式）
    if let Ok(cwd) = std::env::current_dir() {
        for sub in &["python/python.exe", "embedded/python/python.exe"] {
            let p = cwd.join(sub);
            if p.exists() {
                return Some(p.to_string_lossy().to_string());
            }
        }
    }

    // 2. Inno Setup 安装目录（Cursor 的安装包）
    if let Ok(appdata) = std::env::var("LOCALAPPDATA") {
        let inno_python = std::path::PathBuf::from(&appdata)
            .join("ShisanXiang")
            .join("python")
            .join("python.exe");
        if inno_python.exists() {
            return Some(inno_python.to_string_lossy().to_string());
        }
    }

    // 3. 环境变量指定
    if let Ok(p) = std::env::var("OPENCLAW_PYTHON") {
        if !p.is_empty() {
            return Some(p);
        }
    }

    // 4. 系统 Python（验证版本 >= 3.10）
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

    // 逐个检查候选路径
    let mut candidates: Vec<std::path::PathBuf> = Vec::new();

    // 1. 环境变量指定
    if let Ok(p) = std::env::var("OPENCLAW_HOME") {
        candidates.push(std::path::PathBuf::from(p));
    }

    // 2. 当前目录
    if let Ok(cwd) = std::env::current_dir() {
        candidates.push(cwd.clone());
        // 当前目录的父级（从 src-tauri 运行时）
        if let Some(parent) = cwd.parent() {
            candidates.push(parent.to_path_buf());
        }
    }

    // 3. EXE 所在目录及其父级
    if let Ok(exe) = std::env::current_exe() {
        if let Some(dir) = exe.parent() {
            candidates.push(dir.to_path_buf());
            if let Some(parent) = dir.parent() {
                candidates.push(parent.to_path_buf());
            }
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
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
            let show = MenuItem::with_id(app, "show", "显示主窗口", true, None::<&str>)?;
            let restart = MenuItem::with_id(app, "restart", "重启 AI 引擎", true, None::<&str>)?;
            let browser = MenuItem::with_id(app, "browser", "浏览器打开", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "退出", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &restart, &browser, &quit])?;

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
                    "quit" => {
                        let state = app.state::<PythonBackend>();
                        state.stop();
                        app.exit(0);
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

            // ── 启动画面（内联HTML，不依赖文件系统）──
            let splash_html = r#"data:text/html,<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{margin:0;padding:0}body{background:%230b0b16;color:%23e8e8f0;font-family:-apple-system,sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;user-select:none}.logo{font-size:48px;margin-bottom:16px}h1{font-size:20px;font-weight:600;margin-bottom:24px;color:%23c8c8d8}.loader{width:120px;height:4px;background:%231a1a2e;border-radius:2px;overflow:hidden;margin-bottom:12px}.bar{width:40%25;height:100%25;background:linear-gradient(90deg,%237c6aef,%23e94560);border-radius:2px;animation:s 1.2s ease-in-out infinite}@keyframes s{0%25{transform:translateX(-100%25)}100%25{transform:translateX(350%25)}}.hint{font-size:12px;color:%23666}</style></head>
<body><div class="logo">🦞</div><h1>十三香小龙虾 AI</h1><div class="loader"><div class="bar"></div></div><div class="hint">正在启动 AI 引擎...</div></body></html>"#;

            let _splash = WebviewWindowBuilder::new(
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

            // ── 后台等待后端就绪 ──────────────────────
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                if let Some(w) = app_handle.get_webview_window("splash") {
                    let _ = w.close();
                }

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
                        &app_handle,
                        "main",
                        WebviewUrl::External(error_html.parse().unwrap()),
                    )
                    .title("十三香小龙虾 AI")
                    .inner_size(500.0, 400.0)
                    .center()
                    .build();
                    return;
                }

                let ready = wait_for_backend();
                if ready {
                    let _ = WebviewWindowBuilder::new(
                        &app_handle,
                        "main",
                        WebviewUrl::External(APP_URL.parse().unwrap()),
                    )
                    .title("十三香小龙虾 AI")
                    .inner_size(1280.0, 800.0)
                    .min_inner_size(800.0, 600.0)
                    .center()
                    .build();
                } else {
                    let timeout_html = "data:text/html,<!DOCTYPE html><html><head><meta charset=utf-8><style>*{margin:0}body{background:%230b0b16;color:%23e8e8f0;font-family:sans-serif;display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;padding:40px;text-align:center}.icon{font-size:48px;margin-bottom:16px}h1{font-size:20px;margin-bottom:12px}p{color:%23888;font-size:14px;line-height:1.6}code{color:%237c6aef;background:%231a1a2e;padding:2px 6px;border-radius:4px}</style></head><body><div class=icon>⏱️</div><h1>AI 引擎启动超时</h1><p>Python 后端未能在 30 秒内就绪。<br>请尝试手动运行：<br><code>python -m src.server.main</code></p></body></html>";
                    let _ = WebviewWindowBuilder::new(
                        &app_handle,
                        "main",
                        WebviewUrl::External(timeout_html.parse().unwrap()),
                    )
                    .title("十三香小龙虾 AI - 启动超时")
                    .inner_size(500.0, 400.0)
                    .center()
                    .build();
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status, restart_backend])
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
            // 防止 splash 关闭时退出整个应用
            RunEvent::ExitRequested { ref api, .. } => {
                // 只要托盘还在，就不退出
                api.prevent_exit();
            }
            _ => {}
        });
}
