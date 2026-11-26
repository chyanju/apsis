//! apsis-frontend — runs a framework's front-end as a subprocess and reads the IR it writes. Front-ends are
//! Python modules, plus a .NET program for workflows on the .NET SDK of Agent Framework.

use apsis_ir::Program;
use std::path::PathBuf;
use std::process::Command;

/// The supported frameworks, each with the Python module of its front-end.
pub const FRONTENDS: [(&str, &str); 10] = [
    ("haystack", "apsis_haystack"),
    ("langgraph", "apsis_langgraph"),
    ("autogen", "apsis_autogen"),
    ("agent-framework", "apsis_agent_framework"),
    ("langflow", "apsis_langflow"),
    ("flowise", "apsis_flowise"),
    ("crewai", "apsis_crewai"),
    ("llamaindex", "apsis_llamaindex"),
    ("parlant", "apsis_parlant"),
    ("pydantic-ai", "apsis_pydantic_ai"),
];

#[derive(Debug)]
pub enum FrontendError {
    UnknownFramework(String),
    Spawn { program: PathBuf, error: std::io::Error },
    Failed { code: Option<i32>, stderr: String },
    Read(std::io::Error),
    Parse(serde_json::Error),
}

impl std::fmt::Display for FrontendError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FrontendError::UnknownFramework(name) => {
                let known: Vec<&str> = FRONTENDS.iter().map(|(framework, _)| *framework).collect();
                write!(f, "unknown framework `{name}`; expected one of {}", known.join(", "))
            }
            FrontendError::Spawn { program, error } => write!(f, "cannot run `{}`: {error}", program.display()),
            FrontendError::Failed { code, stderr } => {
                let code = code.map_or("a signal".to_string(), |c| format!("exit code {c}"));
                write!(f, "the front-end ended with {code}: {}", stderr.trim())
            }
            FrontendError::Read(e) => write!(f, "cannot read the IR the front-end wrote: {e}"),
            FrontendError::Parse(e) => write!(f, "the front-end wrote invalid IR: {e}"),
        }
    }
}

impl std::error::Error for FrontendError {}

pub fn module_of(framework: &str) -> Option<&'static str> {
    FRONTENDS.iter().find(|(name, _)| *name == framework).map(|(_, module)| *module)
}

/// The Python front-ends run under the `python3` on `PATH`, which needs the framework and the front-end installed.
pub const PYTHON: &str = "python3";

/// The .NET front-end's executable, looked up on `PATH`.
pub const DOTNET_FRONTEND: &str = "apsis-agent-framework-dotnet";

/// `project.csproj:Type.Member`: a C# project and the static member that constructs the workflow.
pub fn is_dotnet_project(source: &str) -> bool {
    source.rsplit_once(':').is_some_and(|(project, _)| project.ends_with(".csproj"))
}

/// `source` is `file.py:attr` or `module:attr`, a `flow.json`, or `project.csproj:Type.Member` (.NET SDK).
pub fn extract(framework: &str, source: &str) -> Result<Program, FrontendError> {
    let module = module_of(framework).ok_or_else(|| FrontendError::UnknownFramework(framework.to_string()))?;
    let mut command = if framework == "agent-framework" && is_dotnet_project(source) {
        Command::new(DOTNET_FRONTEND)
    } else {
        let mut python = Command::new(PYTHON);
        python.args(["-m", module]);
        python
    };
    // The IR goes to a file so that what a framework prints while loading does not mix with the JSON.
    let ir_path = std::env::temp_dir().join(format!("apsis-ir-{}-{module}.json", std::process::id()));
    let program = PathBuf::from(command.get_program());
    let run = command.arg(source).arg("-o").arg(&ir_path).output();
    let result = match run {
        Err(error) => Err(FrontendError::Spawn { program, error }),
        Ok(out) if !out.status.success() => Err(FrontendError::Failed {
            code: out.status.code(),
            stderr: String::from_utf8_lossy(&out.stderr).into_owned(),
        }),
        Ok(_) => std::fs::read_to_string(&ir_path)
            .map_err(FrontendError::Read)
            .and_then(|json| Program::from_json(&json).map_err(FrontendError::Parse)),
    };
    let _ = std::fs::remove_file(&ir_path);
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn every_framework_has_a_front_end_module() {
        assert_eq!(module_of("haystack"), Some("apsis_haystack"));
        assert_eq!(module_of("agent-framework"), Some("apsis_agent_framework"));
        assert_eq!(module_of("unknown"), None);
        assert!(matches!(extract("unknown", "x"), Err(FrontendError::UnknownFramework(_))));
    }

    #[test]
    fn a_csharp_project_goes_to_the_dotnet_front_end() {
        assert!(is_dotnet_project("examples/w/Workflow.csproj:Ns.Case.Build"));
        assert!(!is_dotnet_project("workflow.py:workflow"));
        assert!(!is_dotnet_project("flow.json"));
    }
}
