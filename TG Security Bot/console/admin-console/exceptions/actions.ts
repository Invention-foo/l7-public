'use server'

import { createServerSupabaseClient } from '@/lib/supabase-server'

export async function addException(chatId: string, userId: string) {
  const supabase = await createServerSupabaseClient()
  
  const { error } = await supabase
    .from('athena_secure_tg_exceptions')
    .insert({
      chat_id: chatId,
      user_id: userId
    })

  if (error) throw error
}

export async function removeException(chatId: string, userId: string) {
  const supabase = await createServerSupabaseClient()
  
  // Check if record exists before delete
  const { data: existingRecord } = await supabase
    .from('athena_secure_tg_exceptions')
    .select('*')
    .eq('chat_id', chatId)
    .eq('user_id', userId)
    .single()

  console.log('Existing record:', existingRecord)

  const { error } = await supabase
    .from('athena_secure_tg_exceptions')
    .delete()
    .eq('chat_id', chatId)
    .eq('user_id', userId)

  // Verify deletion
  const { data: checkRecord } = await supabase
    .from('athena_secure_tg_exceptions')
    .select('*')
    .eq('chat_id', chatId)
    .eq('user_id', userId)
    .single()

  console.log('Record after delete attempt:', checkRecord)
  console.log('Delete error:', error)

  if (error) throw error
  if (checkRecord) throw new Error('Record still exists after deletion')
} 