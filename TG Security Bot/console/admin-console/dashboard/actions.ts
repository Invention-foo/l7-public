'use server'

import { createServerSupabaseClient } from '@/lib/supabase-server'

export async function fetchTimeSeriesData(chatId: string, banTimeFrame: string, messageTimeFrame: string) {
  const supabase = await createServerSupabaseClient()
  
  const [banRates, messageRates] = await Promise.all([
    supabase.rpc('get_time_series_data', {
      p_chat_id: chatId,
      p_table: 'moderation',
      p_timeframe: banTimeFrame,
      p_action_type: 'ban'
    }),
    supabase.rpc('get_time_series_data', {
      p_chat_id: chatId,
      p_table: 'message',
      p_timeframe: messageTimeFrame
    })
  ])

  return {
    banRateData: banRates.data || [],
    messageRateData: messageRates.data || []
  }
}

// eslint-disable-next-line @typescript-eslint/no-unused-vars
export async function fetchInitialDashboardData(chatId: string) {
  const supabase = await createServerSupabaseClient()
  
  const [
    // eslint-disable-next-line @typescript-eslint/no-unused-vars   
    { data: bansData, count: totalBans },
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    { data: messagesData, count: totalMessages },
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    { data: spamData, count: spamDeleted },
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    { data: blacklistData, count: blacklistedUsers }
  ] = await Promise.all([
    supabase
      .from('athena_secure_tg_moderation_logs')
      .select('*', { count: 'exact', head: true })
      .eq('action_type', 'ban'),
    supabase
      .from('athena_secure_tg_message_logs')
      .select('*', { count: 'exact', head: true }),
    supabase
      .from('athena_secure_tg_moderation_logs')
      .select('*', { count: 'exact', head: true })
      .eq('action_type', 'delete'),
    supabase
      .from('blacklisted_tg_users')
      .select('*', { count: 'exact', head: true })
  ])

  return {
    totalBans,
    totalMessages,
    spamDeleted,
    blacklistedUsers
  }
} 