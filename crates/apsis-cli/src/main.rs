//! apsis — the command line: `analyze <framework> <source>` runs a front-end first, `check <ir.json | ->` reads IR.
//! Exit code 0: no finding, 1: findings, 2: the workflow could not be read.

use apsis_analysis::{analyze, Finding};
use apsis_frontend::FRONTENDS;
use apsis_ir::{ExecutionModel, Program, Workflow};
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.iter().any(|a| a == "-h" || a == "--help") {
        println!("{}", usage());
        return ExitCode::SUCCESS;
    }
    let json = args.iter().any(|a| a == "--json");
    let positional: Vec<&str> = args.iter().map(String::as_str).filter(|a| *a != "--json").collect();
    match positional.as_slice() {
        ["analyze", framework, source] => match apsis_frontend::extract(framework, source) {
            Ok(program) => report(&program, json),
            Err(e) => fail(&e.to_string(), json),
        },
        ["check", path] => match read_ir(path) {
            Ok(program) => report(&program, json),
            Err(e) => fail(&e, json),
        },
        _ => {
            eprintln!("{}", usage());
            ExitCode::from(2)
        }
    }
}

fn usage() -> String {
    let frameworks: Vec<&str> = FRONTENDS.iter().map(|(framework, _)| *framework).collect();
    format!(
        "usage: apsis analyze <framework> <source> [--json]\n       apsis check <ir.json | -> [--json]\nframeworks: {}",
        frameworks.join(", ")
    )
}

fn read_ir(path: &str) -> Result<Program, String> {
    let json = if path == "-" {
        std::io::read_to_string(std::io::stdin()).map_err(|e| format!("cannot read stdin: {e}"))?
    } else {
        std::fs::read_to_string(path).map_err(|e| format!("cannot read {path}: {e}"))?
    };
    Program::from_json(&json).map_err(|e| format!("invalid IR: {e}"))
}

fn report(program: &Program, json: bool) -> ExitCode {
    let mut findings = analyze(program);
    findings.sort_by(|a, b| (a.detector, a.rule, &a.location).cmp(&(b.detector, b.rule, &b.location)));
    let Some(main) = program.workflows.first() else { return fail("the IR contains no workflow", json) };
    if json {
        report_json(main, &findings);
    } else {
        report_text(main, &findings);
    }
    if findings.is_empty() {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(1)
    }
}

fn report_text(wf: &Workflow, findings: &[Finding]) {
    let model = match &wf.execution_model {
        ExecutionModel::DataflowReadiness => "dataflow",
        ExecutionModel::BspSuperstep => "bulk-synchronous",
        ExecutionModel::GroupChatSpeaker => "group chat",
        ExecutionModel::VisualDataflow => "visual dataflow",
        ExecutionModel::Other(_) => "other",
    };
    let version = wf.framework_version.as_deref().map(|v| format!(" v{v}")).unwrap_or_default();
    println!("apsis · {} · {model}{version} · {} nodes, {} edges", wf.framework, wf.nodes.len(), wf.edges.len());
    match findings.len() {
        0 => println!("no findings."),
        1 => println!("1 finding"),
        n => println!("{n} findings"),
    }
    for f in findings {
        println!("    {} ({}) · {}", f.detector, f.rule, f.location);
        println!("        {}", f.message);
    }
}

fn report_json(wf: &Workflow, findings: &[Finding]) {
    let items: Vec<serde_json::Value> = findings
        .iter()
        .map(|f| serde_json::json!({ "detector": f.detector, "rule": f.rule, "location": f.location, "message": f.message }))
        .collect();
    let doc = serde_json::json!({
        "framework": wf.framework,
        "execution_model": format!("{:?}", wf.execution_model),
        "framework_version": wf.framework_version,
        "nodes": wf.nodes.len(),
        "edges": wf.edges.len(),
        "findings": items,
        "summary": { "total": findings.len() },
    });
    println!("{}", serde_json::to_string_pretty(&doc).unwrap());
}

/// With `--json` the error is a JSON object on stdout, so a caller always gets a document it can parse.
fn fail(message: &str, json: bool) -> ExitCode {
    if json {
        println!("{}", serde_json::json!({ "error": message }));
    } else {
        eprintln!("error: {message}");
    }
    ExitCode::from(2)
}
