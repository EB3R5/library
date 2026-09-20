/*
 * Native launcher for library.app.
 *
 * Must be a compiled Mach-O (not a shell script): macOS TCC attributes file
 * access to the process's code signature, and a zsh-script bundle gets
 * attributed to /bin/zsh — so the app never receives its own Documents-folder
 * grant and dies with EPERM reading the repo it lives in.
 *
 * Tells the shared launcher where the bundle's icon is, cds to the repo (uv
 * resolves the project from cwd; templates/ and gitops are repo-relative) and
 * execs packaging/desktop/launcher.py through uv with the desktop extra.
 */
#include <unistd.h>
#include <stdlib.h>
#include <stdio.h>
#include <libgen.h>
#include <mach-o/dyld.h>

int main(void) {
    char exe[4096]; uint32_t size = sizeof(exe);
    if (_NSGetExecutablePath(exe, &size) != 0) return 1;
    char macos_dir[4096];
    dirname_r(exe, macos_dir);              /* .../Contents/MacOS */
    char contents[4096];
    dirname_r(macos_dir, contents);         /* .../Contents */
    char icon[4600];
    snprintf(icon, sizeof(icon), "%s/Resources/library.icns", contents);
    setenv("LIBRARY_APP_ICON", icon, 1);    /* read by packaging/desktop/launcher.py */

    /* Finder gives a minimal PATH: claude lives in ~/.local/bin, uv in homebrew,
       and any subprocess claude itself spawns expects homebrew on the path too. */
    const char *home = getenv("HOME");
    if (!home) { fputs("HOME not set\n", stderr); return 1; }
    char path[4600];
    snprintf(path, sizeof(path),
             "%s/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin", home);
    setenv("PATH", path, 1);

    /* LIBRARY_REPO overrides the default checkout location. */
    const char *repo = getenv("LIBRARY_REPO");
    char repo_buf[4600];
    if (!repo) {
        snprintf(repo_buf, sizeof(repo_buf), "%s/Documents/GitHub/library", home);
        repo = repo_buf;
    }
    if (chdir(repo) != 0) { perror("chdir"); return 1; }
    execl("/opt/homebrew/bin/uv", "uv", "run", "--extra", "desktop",
          "packaging/desktop/launcher.py", (char *)NULL);
    perror("execl");
    return 1;
}
