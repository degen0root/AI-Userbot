#!/usr/bin/env python3
"""
Test script to verify promoted bot context and generate sample mentions
"""

import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))

from src.ai_userbot.promoted_bot_context import (
    get_bot_context, 
    get_relevant_features, 
    generate_natural_mention,
    is_relevant_to_audience
)

console = Console()


def test_context():
    """Test bot context configuration"""
    console.print("\n[bold cyan]🤖 Testing Moon Temple Bot Context[/bold cyan]\n")
    
    # Get context
    context = get_bot_context()
    
    # Display basic info
    info_panel = Panel(
        f"[bold]Bot:[/bold] {context['username']} ({context['name']})\n"
        f"[bold]Description:[/bold] {context['description']}\n"
        f"[bold]Features:[/bold] {len(context['main_features'])} основных функций\n"
        f"[bold]Target:[/bold] {len(context['target_audience'])} сегментов аудитории",
        title="Основная информация",
        expand=False
    )
    console.print(info_panel)
    
    # Test keywords
    console.print("\n[bold]Тестирование релевантности по ключевым словам:[/bold]\n")
    
    test_phrases = [
        "У меня сегодня первый день цикла",
        "Кто-нибудь следит за лунными днями?",
        "Девочки, какие медитации помогают при ПМС?",
        "Интересно, как луна влияет на женское здоровье",
        "Хочу начать отслеживать свой цикл",
        "Какой сегодня лунный день?",
        "Ищу приложение для женского календаря"
    ]
    
    for phrase in test_phrases:
        words = phrase.lower().split()
        relevant = get_relevant_features(words)
        is_target = is_relevant_to_audience(phrase)
        
        console.print(f"[yellow]Фраза:[/yellow] {phrase}")
        console.print(f"[green]Релевантные функции:[/green] {', '.join(relevant.keys()) if relevant else 'Нет'}")
        console.print(f"[blue]Целевая аудитория:[/blue] {'Да' if is_target else 'Нет'}")
        
        if relevant:
            mention = generate_natural_mention(context_words=words)
            console.print(f"[magenta]Пример упоминания:[/magenta] {mention}")
        console.print()
    
    # Show all features
    console.print("\n[bold]Все функции бота:[/bold]\n")
    
    features_table = Table(title="Функциональность Moon Temple Bot")
    features_table.add_column("Функция", style="cyan", width=25)
    features_table.add_column("Описание", style="green", width=50)
    features_table.add_column("Преимущества", style="yellow", width=40)
    
    for feature_key, feature_data in context['main_features'].items():
        features_table.add_row(
            feature_key.replace('_', ' ').title(),
            feature_data['description'],
            feature_data['benefits']
        )
    
    console.print(features_table)
    
    # Generate sample mentions
    console.print("\n[bold]Примеры естественных упоминаний:[/bold]\n")
    
    topics = ["цикл", "луна", "медитация", "женское здоровье", "астрология"]
    
    for topic in topics:
        mention = generate_natural_mention(topic)
        console.print(f"[cyan]Тема '{topic}':[/cyan] {mention}")
    
    # Random mentions
    console.print("\n[bold]Случайные упоминания:[/bold]\n")
    for i in range(5):
        mention = generate_natural_mention()
        console.print(f"{i+1}. {mention}")


if __name__ == "__main__":
    try:
        test_context()
    except Exception as e:
        console.print(f"\n[red]Ошибка: {e}[/red]")
        import traceback
        traceback.print_exc()
