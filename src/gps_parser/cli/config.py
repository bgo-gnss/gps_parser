"""GPS configuration deployment CLI."""

import argparse
import configparser
import os
import re
import socket
import sys
from pathlib import Path
from typing import Dict, Optional


class ConfigDeployer:
    """Handles template-based configuration deployment."""

    def __init__(self, config_data_dir: Optional[Path] = None):
        """Initialize deployer.

        Args:
            config_data_dir: Path to gps-config-data directory.
                            If None, auto-detects based on GPS_CONFIG_PATH.
        """
        self.config_data_dir = self._find_config_data_dir(config_data_dir)
        self.environments_dir = self.config_data_dir / "environments"
        self.deploy_dir = self._get_deploy_dir()

    def _find_config_data_dir(self, config_data_dir: Optional[Path]) -> Path:
        """Find gps-config-data directory."""
        if config_data_dir:
            return Path(config_data_dir)

        # Try GPS_CONFIG_PATH
        if gps_config := os.environ.get("GPS_CONFIG_PATH"):
            return Path(gps_config)

        # Try default locations
        default_user = Path.home() / ".config" / "gpsconfig"
        default_system = Path("/etc/gpsconfig")

        if default_user.exists():
            return default_user
        elif default_system.exists():
            return default_system
        else:
            # Assume we're in development and look relative to package
            package_dir = Path(__file__).parent.parent.parent.parent.parent
            config_dir = package_dir / "gps-config-data"
            if config_dir.exists():
                return config_dir

        raise FileNotFoundError(
            "Could not find gps-config-data directory. "
            "Set GPS_CONFIG_PATH or ensure configs are in ~/.config/gpsconfig/"
        )

    def _get_deploy_dir(self) -> Path:
        """Get deployment directory (same as config data dir)."""
        return self.config_data_dir

    def auto_detect_environment(self) -> str:
        """Auto-detect environment from hostname."""
        hostname = socket.gethostname()

        # Check if there's an exact match
        env_file = self.environments_dir / f"{hostname}.env"
        if env_file.exists():
            return hostname

        # Check for partial matches (e.g., rek.vedur.is matches rek)
        for env_file in self.environments_dir.glob("*.env"):
            env_name = env_file.stem
            if env_name in hostname or hostname in env_name:
                return env_name

        # Default fallbacks
        if "vedur.is" in hostname:
            return "production"
        else:
            return "laptop-bgo"

    def load_environment(self, env_name: str) -> Dict[str, str]:
        """Load environment configuration from .env file.

        Args:
            env_name: Name of environment (e.g., 'production', 'laptop-bgo')

        Returns:
            Dictionary of variable_name -> value mappings
        """
        env_file = self.environments_dir / f"{env_name}.env"
        if not env_file.exists():
            raise FileNotFoundError(f"Environment file not found: {env_file}")

        config = configparser.ConfigParser()
        config.read(env_file)

        # Flatten all sections into a single dict with two naming schemes:
        # 1. section_key (e.g., scheduler_database)
        # 2. key (e.g., database) - for backwards compatibility
        variables = {}
        for section in config.sections():
            for key, value in config.items(section):
                # Add with section prefix (preferred)
                prefixed_key = f"{section}_{key}"
                variables[prefixed_key] = value

                # Also add without prefix for simple keys (may have collisions)
                if key not in variables:
                    variables[key] = value

        return variables

    def find_templates(self) -> list[Path]:
        """Find all template files in config data directory.

        Returns:
            List of template file paths (*.template files)
        """
        return list(self.config_data_dir.glob("*.template"))

    def render_template(self, template_path: Path, variables: Dict[str, str]) -> str:
        """Render a template file with variables.

        Args:
            template_path: Path to template file
            variables: Dictionary of variable_name -> value mappings

        Returns:
            Rendered content as string
        """
        content = template_path.read_text()

        # Replace {{variable}} with values
        def replace_var(match):
            var_name = match.group(1)
            if var_name not in variables:
                raise ValueError(
                    f"Variable {{{{{{var_name}}}}}} not found in environment. "
                    f"Available: {', '.join(sorted(variables.keys()))}"
                )
            return variables[var_name]

        rendered = re.sub(r"\{\{(\w+)\}\}", replace_var, content)
        return rendered

    def deploy_template(
        self, template_path: Path, variables: Dict[str, str], dry_run: bool = False
    ) -> tuple[Path, bool]:
        """Deploy a single template file.

        Args:
            template_path: Path to template file
            variables: Dictionary of variable_name -> value mappings
            dry_run: If True, don't write files

        Returns:
            Tuple of (output_path, changed) where changed indicates if content differs
        """
        # Determine output path (remove .template suffix)
        output_filename = template_path.name.replace(".template", "")
        output_path = self.deploy_dir / output_filename

        # Render template
        rendered_content = self.render_template(template_path, variables)

        # Check if content has changed
        changed = True
        if output_path.exists():
            existing_content = output_path.read_text()
            changed = existing_content != rendered_content

        # Write file (unless dry-run)
        if not dry_run:
            output_path.write_text(rendered_content)

        return output_path, changed

    def show_diff(self, template_path: Path, variables: Dict[str, str]) -> None:
        """Show diff between current and rendered template.

        Args:
            template_path: Path to template file
            variables: Dictionary of variable_name -> value mappings
        """
        output_filename = template_path.name.replace(".template", "")
        output_path = self.deploy_dir / output_filename

        rendered_content = self.render_template(template_path, variables)

        if not output_path.exists():
            print(f"  New file: {output_path.name}")
            print("  --- /dev/null")
            print(f"  +++ {output_path.name}")
            for line in rendered_content.splitlines()[:10]:  # Show first 10 lines
                print(f"  + {line}")
            if len(rendered_content.splitlines()) > 10:
                print(f"  ... ({len(rendered_content.splitlines()) - 10} more lines)")
        else:
            existing_content = output_path.read_text()
            if existing_content != rendered_content:
                print(f"  Modified: {output_path.name}")
                # Simple line-by-line diff
                existing_lines = existing_content.splitlines()
                rendered_lines = rendered_content.splitlines()

                for i, (old, new) in enumerate(zip(existing_lines, rendered_lines)):
                    if old != new:
                        print(f"  Line {i+1}:")
                        print(f"  - {old}")
                        print(f"  + {new}")
            else:
                print(f"  Unchanged: {output_path.name}")

    def deploy(
        self,
        env_name: Optional[str] = None,
        dry_run: bool = False,
        show_diff: bool = False,
        verbose: bool = False,
    ) -> int:
        """Deploy configuration from templates.

        Args:
            env_name: Environment name (auto-detects if None)
            dry_run: If True, don't write files
            show_diff: If True, show diffs before deploying
            verbose: If True, show detailed output

        Returns:
            Exit code (0 for success)
        """
        # Auto-detect environment if not specified
        if not env_name:
            env_name = self.auto_detect_environment()
            if verbose:
                print(f"Auto-detected environment: {env_name}")

        # Load environment variables
        try:
            variables = self.load_environment(env_name)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

        if verbose:
            print(f"Loaded {len(variables)} variables from {env_name}.env")

        # Find templates
        templates = self.find_templates()
        if not templates:
            print("Warning: No template files found", file=sys.stderr)
            return 0

        if verbose:
            print(f"Found {len(templates)} template files")

        # Show diffs if requested
        if show_diff:
            print(f"\nConfiguration changes for environment '{env_name}':\n")
            for template in templates:
                try:
                    self.show_diff(template, variables)
                except Exception as e:
                    print(f"Error showing diff for {template.name}: {e}", file=sys.stderr)
                    return 1
            print()

        # Deploy templates
        if dry_run:
            print(f"DRY RUN: Would deploy {len(templates)} templates to {self.deploy_dir}")
        else:
            if verbose:
                print(f"\nDeploying to {self.deploy_dir}...\n")

        deployed = []
        changed = []

        for template in templates:
            try:
                output_path, has_changed = self.deploy_template(template, variables, dry_run)
                deployed.append(output_path)
                if has_changed:
                    changed.append(output_path)

                if verbose or dry_run:
                    status = "would create" if dry_run and not output_path.exists() else (
                        "would update" if dry_run else "created" if not output_path.exists() else
                        "updated" if has_changed else "unchanged"
                    )
                    print(f"  {status}: {output_path.name}")

            except Exception as e:
                print(f"Error deploying {template.name}: {e}", file=sys.stderr)
                return 1

        # Summary
        if not dry_run:
            print(f"\n✓ Successfully deployed {len(deployed)} configuration files")
            if changed:
                print(f"  {len(changed)} files updated, {len(deployed) - len(changed)} unchanged")
        else:
            print(f"\nDry run complete. Would deploy {len(deployed)} files.")

        return 0


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="GPS configuration deployment tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Auto-detect environment and deploy
  gps-config deploy

  # Deploy specific environment
  gps-config deploy --env rek.vedur.is

  # Preview changes without deploying
  gps-config deploy --dry-run --show-diff

  # Deploy with verbose output
  gps-config deploy --env production --verbose
        """
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Deploy command
    deploy_parser = subparsers.add_parser(
        "deploy",
        help="Deploy configuration from templates"
    )
    deploy_parser.add_argument(
        "--env",
        help="Environment name (auto-detects if not specified)"
    )
    deploy_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing files"
    )
    deploy_parser.add_argument(
        "--show-diff",
        action="store_true",
        help="Show diff between current and new configuration"
    )
    deploy_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output"
    )
    deploy_parser.add_argument(
        "--config-dir",
        type=Path,
        help="Path to gps-config-data directory (auto-detects if not specified)"
    )

    args = parser.parse_args()

    # Show help if no command specified
    if not args.command:
        parser.print_help()
        return 0

    # Execute deploy command
    if args.command == "deploy":
        deployer = ConfigDeployer(config_data_dir=args.config_dir)
        return deployer.deploy(
            env_name=args.env,
            dry_run=args.dry_run,
            show_diff=args.show_diff,
            verbose=args.verbose,
        )

    return 0


def cli():
    """CLI entry point for console script."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
