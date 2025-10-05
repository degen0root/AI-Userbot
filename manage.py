#!/usr/bin/env python3
"""
Management script for AI UserBot
"""

import asyncio
import argparse
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table

from src.ai_userbot.config import load_config
from src.ai_userbot.database import ChatDatabase

console = Console()


async def show_stats(config_path: Path):
    """Show bot statistics"""
    config = load_config(config_path)
    db = ChatDatabase()
    await db.initialize()
    
    # Get active chats
    active_chats = await db.get_active_chats()
    
    # Create table
    table = Table(title="AI UserBot Statistics")
    table.add_column("Chat ID", style="cyan")
    table.add_column("Title", style="green")
    table.add_column("Members", justify="right")
    table.add_column("Messages Sent", justify="right")
    table.add_column("Promotions", justify="right")
    table.add_column("Status", style="yellow")
    
    total_messages = 0
    total_promotions = 0
    
    for chat in active_chats:
        table.add_row(
            str(chat.chat_id),
            chat.title or "Unknown",
            str(chat.members_count),
            str(chat.total_messages_sent),
            str(chat.total_promotions_sent),
            "Active" if chat.is_active else "Inactive"
        )
        total_messages += chat.total_messages_sent
        total_promotions += chat.total_promotions_sent
    
    console.print(table)
    console.print(f"\n[bold]Total active chats:[/bold] {len(active_chats)}")
    console.print(f"[bold]Total messages sent:[/bold] {total_messages}")
    console.print(f"[bold]Total promotions:[/bold] {total_promotions}")
    
    if total_messages > 0:
        promotion_rate = (total_promotions / total_messages) * 100
        console.print(f"[bold]Promotion rate:[/bold] {promotion_rate:.2f}%")
    
    await db.close()


async def clear_session(config_path: Path):
    """Clear Pyrogram session"""
    config = load_config(config_path)
    session_file = Path(f"{config.telegram.session_name}.session")
    
    if session_file.exists():
        session_file.unlink()
        console.print("[green]Session cleared successfully[/green]")
    else:
        console.print("[yellow]No session file found[/yellow]")


async def reset_database():
    """Reset the database"""
    db_file = Path("userbot.db")
    
    if db_file.exists():
        confirm = console.input("[red]Are you sure you want to reset the database? (yes/no): [/red]")
        if confirm.lower() == "yes":
            db_file.unlink()
            console.print("[green]Database reset successfully[/green]")
        else:
            console.print("[yellow]Database reset cancelled[/yellow]")
    else:
        console.print("[yellow]No database file found[/yellow]")


async def test_llm(config_path: Path):
    """Test LLM connection"""
    from src.ai_userbot.llm import create_llm_client, LLMRequest
    
    config = load_config(config_path)
    
    llm_config = {
        "provider": config.llm.provider,
        "api_key": config.llm.api_key,
        "model": config.llm.model,
        "temperature": config.llm.temperature,
        "base_url": config.llm.base_url
    }
    
    console.print(f"[cyan]Testing LLM provider:[/cyan] {config.llm.provider}")
    console.print(f"[cyan]Model:[/cyan] {config.llm.model}")
    
    try:
        llm = create_llm_client(llm_config)
        request = LLMRequest(
            prompt="Привет! Как дела?",
            temperature=0.7,
            max_tokens=100
        )
        
        console.print("\n[yellow]Sending test prompt...[/yellow]")
        response = await llm.generate_async(request)
        
        console.print("\n[green]LLM Response:[/green]")
        console.print(response)
        console.print("\n[green]✓ LLM connection successful![/green]")
        
    except Exception as e:
        console.print(f"\n[red]✗ LLM connection failed:[/red] {e}")


async def main():
    parser = argparse.ArgumentParser(description="AI UserBot Management Tool")
    parser.add_argument("--config", default="configs/config.yaml", help="Path to config file")
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Stats command
    subparsers.add_parser("stats", help="Show bot statistics")
    
    # Clear session command
    subparsers.add_parser("clear-session", help="Clear Pyrogram session")
    
    # Reset database command
    subparsers.add_parser("reset-db", help="Reset the database")
    
    # Test LLM command
    subparsers.add_parser("test-llm", help="Test LLM connection")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    config_path = Path(args.config)
    if not config_path.exists() and args.command != "reset-db":
        console.print(f"[red]Config file not found:[/red] {config_path}")
        sys.exit(1)
    
    try:
        if args.command == "stats":
            await show_stats(config_path)
        elif args.command == "clear-session":
            await clear_session(config_path)
        elif args.command == "reset-db":
            await reset_database()
        elif args.command == "test-llm":
            await test_llm(config_path)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
