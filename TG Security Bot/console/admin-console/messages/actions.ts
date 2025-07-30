'use server'

import { createServerSupabaseClient } from '@/lib/supabase-server'

export async function fetchMessages(chatId: string, limit: number) {
  const supabase = await createServerSupabaseClient()
  
  const { data: messages, error } = await supabase
    .from('athena_secure_tg_message_logs')
    .select(`
      id,
      message_text,
      created_at,
      athena_secure_tg_logs!inner(
        chat_id,
        user_id,
        content
      )
    `)
    .eq('athena_secure_tg_logs.chat_id', chatId)
    .order('created_at', { ascending: false })
    .limit(limit)

  if (error) throw error
  return messages
}

export async function searchMessages(chatId: string, query: string) {
  const supabase = await createServerSupabaseClient()
  
  const { data: messages, error } = await supabase
    .rpc('search_messages', {
      p_chat_id: chatId,
      p_query: query
    })

  if (error) throw error
  return messages
} 