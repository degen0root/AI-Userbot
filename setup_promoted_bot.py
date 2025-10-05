#!/usr/bin/env python3
"""
Interactive script to setup promoted bot configuration
"""

import os
import sys
from pathlib import Path
from rich.console import Console
from rich.prompt import Prompt, Confirm

console = Console()


def main():
    console.print("[bold cyan]🤖 AI UserBot - Настройка продвигаемого бота[/bold cyan]\n")
    
    # Check if .env exists
    env_path = Path(".env")
    if not env_path.exists():
        console.print("[yellow]Файл .env не найден. Создаю из примера...[/yellow]")
        example_path = Path(".env.example")
        if example_path.exists():
            env_path.write_text(example_path.read_text())
        else:
            console.print("[red]Ошибка: .env.example не найден![/red]")
            sys.exit(1)
    
    # Read current .env
    env_content = env_path.read_text()
    env_lines = env_content.splitlines()
    
    # Ask for bot details
    console.print("[bold]Введите информацию о боте, который хотите продвигать:[/bold]\n")
    
    bot_username = Prompt.ask(
        "Username бота (с @)",
        default="@LunnyiHramBot"
    )
    
    bot_name = Prompt.ask(
        "Название бота",
        default="Лунный Храм"
    )
    
    console.print(f"\n[green]Отлично! Буду продвигать бота {bot_username} ({bot_name})[/green]\n")
    
    # Update .env
    updated_lines = []
    username_updated = False
    name_updated = False
    
    for line in env_lines:
        if line.startswith("PROMOTED_BOT_USERNAME="):
            updated_lines.append(f"PROMOTED_BOT_USERNAME={bot_username}")
            username_updated = True
        elif line.startswith("PROMOTED_BOT_NAME="):
            updated_lines.append(f'PROMOTED_BOT_NAME="{bot_name}"')
            name_updated = True
        else:
            updated_lines.append(line)
    
    # Add if not found
    if not username_updated:
        updated_lines.append(f"\n# Promoted bot information")
        updated_lines.append(f"PROMOTED_BOT_USERNAME={bot_username}")
    if not name_updated:
        updated_lines.append(f'PROMOTED_BOT_NAME="{bot_name}"')
    
    # Write back
    env_path.write_text("\n".join(updated_lines))
    console.print("[green]✓ Файл .env обновлен[/green]\n")
    
    # Ask about customizing context
    if Confirm.ask("Хотите настроить детальное описание бота?"):
        console.print("\n[yellow]Для детальной настройки отредактируйте файл:[/yellow]")
        console.print("[cyan]src/ai_userbot/promoted_bot_context.py[/cyan]\n")
        console.print("Там вы можете указать:")
        console.print("• Подробное описание функционала")
        console.print("• Целевую аудиторию")
        console.print("• Ключевые преимущества")
        console.print("• Примеры естественных упоминаний\n")
    
    # Show next steps
    console.print("[bold]Следующие шаги:[/bold]")
    console.print("1. Убедитесь, что указали Telegram API credentials в .env")
    console.print("2. Выберите и настройте LLM провайдера (OpenAI/Anthropic/Google)")
    console.print("3. Запустите бота: [cyan]python run.py[/cyan]")
    console.print("\n[dim]Удачи в продвижении![/dim] 🚀")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Отменено[/yellow]")
    except Exception as e:
        console.print(f"\n[red]Ошибка: {e}[/red]")
        sys.exit(1)
