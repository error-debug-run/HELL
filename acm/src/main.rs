use acm::{classify_all, AppEntry};  // from lib, no mod declaration
use serde_json::Value;
use std::io::{self, Read};
use std::{env, fs};

fn main() {
    let args: Vec<String> = env::args().collect();
    let raw = if args.len() > 1 {
        fs::read_to_string(&args[1]).unwrap_or_else(|e| {
            eprintln!("error reading '{}': {}", args[1], e);
            std::process::exit(1);
        })
    } else {
        let mut buf = String::new();
        io::stdin().read_to_string(&mut buf).expect("stdin read failed");
        buf
    };
    let raw = raw.trim();
    if raw.is_empty() {
        eprintln!("usage: app_categorizer [file.json]  OR  echo '...' | app_categorizer");
        std::process::exit(1);
    }
    let entries: Vec<AppEntry> = match serde_json::from_str::<Value>(raw) {
        Ok(Value::Array(arr)) => {
            serde_json::from_value(Value::Array(arr)).unwrap_or_else(|e| {
                eprintln!("deserialize error: {}", e);
                std::process::exit(1);
            })
        }
        Ok(Value::Object(ref obj)) if obj.contains_key("installed_apps") => {
            serde_json::from_value::<Vec<AppEntry>>(obj["installed_apps"].clone())
                .unwrap_or_else(|e| {
                    eprintln!("deserialize error (installed_apps): {}", e);
                    std::process::exit(1);
                })
        }
        Ok(obj @ Value::Object(_)) => {
            vec![serde_json::from_value::<AppEntry>(obj).unwrap_or_else(|e| {
                eprintln!("deserialize error (single entry): {}", e);
                std::process::exit(1);
            })]
        }
        Ok(_) => {
            eprintln!("expected a JSON object or array");
            std::process::exit(1);
        }
        Err(e) => {
            eprintln!("invalid JSON: {}", e);
            std::process::exit(1);
        }
    };
    let results = classify_all(&entries);
    println!("{}", serde_json::to_string_pretty(&results).unwrap());
}