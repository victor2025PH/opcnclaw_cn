use std::process::{Child, Command};
use std::sync::Mutex;
use tauri::{Manager, RunEvent};

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

    /// 启动 Python FastAPI 后端
    fn start(&self) -> Result<(), String> {
        let mut guard = self.child.lock().map_err(|e| e.to_string())?;
        if guard.is_some() {
            return Ok(()); // 已在运行
        }

        // 查找 Python：优先用内嵌的，其次系统 Python
        let python = find_python();

        let child = Command::new(&python)
            .args(["-m", "src.server.main"])
            .env("PYTHONPATH", ".")
            .spawn()
            .map_err(|e| format!("Failed to start Python backend ({}): {}", python, e))?;

        *guard = Some(child);
        Ok(())
    }

    /// 停止 Python 后端
    fn stop(&self) {
        if let Ok(mut guard) = self.child.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}

impl Drop for PythonBackend {
    fn drop(&mut self) {
        self.stop();
    }
}

/// 查找可用的 Python 路径
fn find_python() -> String {
    // 1. 内嵌 Python（安装包自带）
    let embedded = std::env::current_dir()
        .ok()
        .map(|d| d.join("python").join("python.exe"));
    if let Some(ref p) = embedded {
        if p.exists() {
            return p.to_string_lossy().to_string();
        }
    }

    // 2. 系统 Python
    for name in &["python", "python3", "python3.11", "python3.12", "python3.13"] {
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

/// 查询后端状态
#[tauri::command]
fn backend_status(state: tauri::State<PythonBackend>) -> String {
    let guard = state.child.lock().unwrap();
    if guard.is_some() {
        "running".to_string()
    } else {
        "stopped".to_string()
    }
}

/// 重启后端
#[tauri::command]
fn restart_backend(state: tauri::State<PythonBackend>) -> Result<String, String> {
    state.stop();
    std::thread::sleep(std::time::Duration::from_secs(1));
    state.start()?;
    Ok("restarted".to_string())
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let backend = PythonBackend::new();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_shell::init())
        .manage(backend)
        .setup(|app| {
            // 启动 Python 后端
            let state = app.state::<PythonBackend>();
            if let Err(e) = state.start() {
                eprintln!("Warning: Python backend start failed: {}", e);
                // 不阻塞启动——用户可能已经手动启动了后端
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_status, restart_backend])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let RunEvent::ExitRequested { .. } = event {
                // 退出时停止 Python 后端
                let state = app_handle.state::<PythonBackend>();
                state.stop();
            }
        });
}
