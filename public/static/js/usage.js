function formatToken(num) {
  if (!num) return '0';
  if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
  if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
  return num.toString();
}

async function loadUsageStats() {
  try {
    const response = await fetch('/api/usage-stats/');
    if (!response.ok) return;
    const data = await response.json();

    document.querySelector('#usage-input').textContent = formatToken(data.total_input_tokens);
    document.querySelector('#usage-output').textContent = formatToken(data.total_output_tokens);
    document.querySelector('#usage-total').textContent = formatToken(data.total_tokens);
  } catch (error) {
    console.error('Error fetching usage data:', error);
  }
}

loadUsageStats();