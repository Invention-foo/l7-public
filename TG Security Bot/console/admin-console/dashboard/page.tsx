import { createServerSupabaseClient } from '@/lib/supabase-server'
import { DashboardClient } from './dashboard-client'
import { fetchInitialDashboardData, fetchTimeSeriesData } from './actions'

export default async function DashboardPage() {
  try {
    const supabase = await createServerSupabaseClient()
    
    const { data: { user } } = await supabase.auth.getUser()
    if (!user) throw new Error('Not authenticated')

    const { data: userChat } = await supabase
      .from('verified_projects_accounts')
      .select('telegram_chat_id')
      .eq('auth_id', user.id)
      .single()
    
    if (!userChat) throw new Error('No telegram chat found')

    const stats = await fetchInitialDashboardData(userChat.telegram_chat_id)
    const { banRateData, messageRateData } = await fetchTimeSeriesData(
      userChat.telegram_chat_id,
      'daily',
      'daily'
    )

    const dashboardData = {
      userChat: {
        usersBanned: stats.totalBans ?? 0,
        messagesScanned: stats.totalMessages ?? 0,
        spamMessagesDeleted: stats.spamDeleted ?? 0,
      },
      partnerNetwork: {
        totalUsersBanned: stats.totalBans ?? 0,
        totalMessagesScanned: stats.totalMessages ?? 0,
        totalSpamDeleted: stats.spamDeleted ?? 0,
        globalBlacklistedUsers: stats.blacklistedUsers ?? 0,
      },
      banRateOverTime: banRateData,
      messageRateOverTime: messageRateData,
      chatId: userChat.telegram_chat_id
    }

    return <DashboardClient data={dashboardData} />
  } catch (error) {
    console.error('Dashboard error:', error)
    throw error
  }
} 