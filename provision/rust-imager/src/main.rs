//! カーネルの ELF を、bootloader の BIOS のディスクイメージにする。
use std::path::PathBuf;
use std::process::ExitCode;

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let [kernel, out] = args.as_slice() else {
        eprintln!("usage: swa-imager <kernel> <image>");
        return ExitCode::from(2);
    };
    match bootloader::BiosBoot::new(&PathBuf::from(kernel)).create_disk_image(&PathBuf::from(out)) {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("swa-imager: {error:#}");
            ExitCode::FAILURE
        }
    }
}
