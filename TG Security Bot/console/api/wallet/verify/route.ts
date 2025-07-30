import { NextResponse } from 'next/server';
import { createClient } from '@supabase/supabase-js';
import { ethers } from 'ethers';
import { SignJWT } from 'jose';

// Initialize Supabase admin client (server-side only)
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || '';
const supabaseServiceKey = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

// Make sure we have the required environment variables
if (!supabaseUrl || !supabaseServiceKey) {
  console.error("Missing Supabase environment variables");
}

const supabaseAdmin = createClient(supabaseUrl, supabaseServiceKey);

// SMITH token contract details
const SMITH_TOKEN_ADDRESS = "0x991ab5d07f28232ec1677e2c13239fb9b4b9ccb7";
const SMITH_TOKEN_ABI = [
  "function balanceOf(address owner) view returns (uint256)"
];
const SMITH_THRESHOLD = 250000;

export async function POST(request: Request) {
  try {
    // Check if Supabase is properly initialized
    if (!supabaseUrl || !supabaseServiceKey) {
      return NextResponse.json({ 
        success: false, 
        message: "Server configuration error" 
      }, { status: 500 });
    }
    
    const { walletAddress, signature, nonce } = await request.json();
    
    // Verify signature
    const message = `Sign this message to authenticate with NeoGuard: ${nonce}`;
    const recoveredAddress = ethers.verifyMessage(message, signature);
    
    if (recoveredAddress.toLowerCase() !== walletAddress.toLowerCase()) {
      return NextResponse.json({ 
        success: false, 
        message: "Signature verification failed" 
      }, { status: 401 });
    }
    
    // Check SMITH balance
    const provider = new ethers.JsonRpcProvider("https://mainnet.base.org");
    const smithContract = new ethers.Contract(
      SMITH_TOKEN_ADDRESS,
      SMITH_TOKEN_ABI,
      provider
    );
    
    const balanceBigInt = await smithContract.balanceOf(walletAddress);
    const balance = Number(ethers.formatUnits(balanceBigInt, 18));
    const meetsThreshold = balance >= SMITH_THRESHOLD;
    
    // Update user_wallets
    const { error: walletError } = await supabaseAdmin
      .from("user_wallets")
      .upsert({
        wallet_address: walletAddress,
        chain_id: "0x14a33", // Base chain ID
        smith_balance: balance,
        updated_at: new Date().toISOString()
      }, { onConflict: "wallet_address" });
    
    if (walletError) {
      console.error("Error updating wallet:", walletError);
      return NextResponse.json({ 
        success: false, 
        message: "Database error" 
      }, { status: 500 });
    }
    
    // Check if user exists
    const { data: existingUser } = await supabaseAdmin
      .from("neoguard_users")
      .select("id")
      .eq("wallet_address", walletAddress)
      .single();
    
    const userExists = !!existingUser;
    
    // Update or create user
    if (userExists) {
      await supabaseAdmin
        .from("neoguard_users")
        .update({ 
          is_eligible: meetsThreshold,
          updated_at: new Date().toISOString()
        })
        .eq("wallet_address", walletAddress);
    } else if (meetsThreshold) {
      await supabaseAdmin
        .from("neoguard_users")
        .insert({
          wallet_address: walletAddress,
          is_eligible: true,
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString()
        });
    }
    
    // Create a JWT token
    const secret = new TextEncoder().encode(process.env.JWT_SECRET || 'your-secret-key');
    const token = await new SignJWT({ 
      walletAddress: walletAddress,
      isEligible: meetsThreshold 
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setIssuedAt()
      .setExpirationTime('7d')
      .sign(secret);
    
    return NextResponse.json({
      success: true,
      userExists,
      isEligible: meetsThreshold,
      balance,
      formattedBalance: balance.toLocaleString(),
      token // Return the JWT token
    });
  } catch (error) {
    console.error("Wallet verification error:", error);
    return NextResponse.json({ 
      success: false, 
      message: "Server error" 
    }, { status: 500 });
  }
} 