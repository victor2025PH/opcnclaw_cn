use std::process::{Child, Command};
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

const BACKEND_PORT: u16 = 8766;
const BACKEND_URL: &str = "http://localhost:8766";
const APP_URL: &str = "http://localhost:8766/app";
const HEALTH_URL: &str = "http://localhost:8766/api/health";
const HEALTH_TIMEOUT: Duration = Duration::from_secs(30);
const HEALTH_POLL: Duration = Duration::from_millis(500);

/// Python 后端进程管理
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

        // 检查端口是否已被占用（可能手动启动了后端）
        if check_port_open(BACKEND_PORT) {
            return Ok(());
        }

        let python = find_python();
        let child = Command::new(&python)
            .args(["-m", "src.server.main"])
            .env("PYTHONPATH", ".")
            .spawn()
            .map_err(|e| format!("启动失败 ({}): {}", python, e))?;

        *guard = Some(child);
        Ok(())
    }

    fn stop(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                // 优雅退出：先尝试正常关闭
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

fn find_python() -> String {
    // 1. 内嵌 Python
    if let Ok(cwd) = std::env::current_dir() {
        let embedded = cwd.join("python").join("python.exe");
        if embedded.exists() {
            return embedded.to_string_lossy().to_string();
        }
    }
    // 2. 系统 Python
    for name in &["python", "python3"] {
        if Command::new(name)
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            return name.to_string();
        }
    }
    "python".to_string()
}

fn check_port_open(port: u16) -> bool {
    std::net::TcpStream::connect_timeout(
        &format!("127.0.0.1:{}", port).parse().unwrap(),
        Duration::from_millis(200),
    )
    .is_ok()
}

/// 等待后端健康检查通过
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = PythonBackend::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(backend)
        .setup(|app| {
            let state = app.state::<PythonBackend>();

            // 1. 启动 Python 后端
            if let Err(e) = state.start() {
                eprintln!("Warning: {}", e);
            }

            // 2. 创建启动画面窗口
            let splash = WebviewWindowBuilder::new(
                app,
                "splash",
                WebviewUrl::App("splash.html".into()),
            )
            .title("十三香小龙虾 AI")
            .inner_size(400.0, 300.0)
            .center()
            .decorations(false)
            .resizable(false)
            .build()?;

            // 3. 后台线程等待后端就绪
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                let ready = wait_for_backend();

                // 关闭启动画面
                if let Some(w) = app_handle.get_webview_window("splash") {
                    let _ = w.close();
                }

                // 打开主窗口
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
                    // 后端超时，显示错误
                    let _ = WebviewWindowBuilder::new(
                        &app_handle,
                        "main",
                        WebviewUrl::App("error.html".into()),
                    )
                    .title("十三香小龙虾 AI - 启动失败")
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
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<PythonBackend>();
                state.stop();
            }
        });
}
