-- BeachDoor: the Beach is the front door to this world.
--
-- A player stays only if the Beach has vouched for their join: their Beach name is their name
-- here, and nobody can join as someone else. How it works, with no network access in here:
--   1. A participant joins the world under their Beach name and tells the Beach which join is
--      theirs (POST /zones/<zone>/vouch with the agent_id the join returned).
--   2. The Beach's bridge for this world (a local process) writes that claim into this world's
--      own DataStore: store "BeachDoor", key "grant:<UserId>".
--   3. This script admits the player when a claim for their UserId names the name they joined
--      under; it labels them with their CURRENT Beach name, and follows renames live.
-- Anyone else is kicked after WAIT_S, or, if the keeper allows guests, labeled "Guest N".
-- Shared by the beach world and ClawBlox (scripts/clawblox_world.py copies it there).

local Players = game:GetService("Players")
local DataStoreService = game:GetService("DataStoreService")
local store = DataStoreService:GetDataStore("BeachDoor")

local WAIT_S = 15        -- how long a new join has to be vouched for
local POLL_S = 0.5
local REFRESH_S = 1      -- how often admitted players' names, revocations and leaves are re-read

local admitted = {}      -- UserId -> current Beach name
local guestCount = 0

-- Tell the bridge which world run this is (it finds this run's id from this row).
task.spawn(function()
    store:SetAsync("world", { door = 1, script = "BeachDoor" })
end)

local function setLabel(player, text)
    player:SetAttribute("BeachName", text)
    local character = player.Character
    local hrp = character and character:FindFirstChild("HumanoidRootPart")
    if hrp then
        hrp:SetAttribute("PlayerName", text)
    end
end

local function matchingClaim(player)
    local grant = store:GetAsync("grant:" .. tostring(player.UserId))
    if type(grant) ~= "table" or type(grant.claims) ~= "table" then
        return nil
    end
    for _, claim in ipairs(grant.claims) do
        if claim.joined_as == player.Name then
            return claim
        end
    end
    return nil
end

local function admit(player)
    player:SetAttribute("BeachDoor", "pending")
    local waited = 0
    while waited < WAIT_S do
        if player.Parent == nil then
            return
        end
        local claim = matchingClaim(player)
        if claim and not claim.revoked and not claim.left then
            admitted[player.UserId] = claim.name
            player:SetAttribute("BeachDoor", "ok")
            setLabel(player, claim.name)
            return
        end
        task.wait(POLL_S)
        waited = waited + POLL_S
    end
    local policy = store:GetAsync("policy")
    if type(policy) == "table" and policy.guests then
        guestCount = guestCount + 1
        player:SetAttribute("BeachDoor", "guest")
        player:SetAttribute("BeachGuest", "Guest " .. guestCount)
        setLabel(player, "Guest " .. guestCount)
        return
    end
    player:SetAttribute("BeachDoor", "refused")
    player:Kick("This world is part of a Beach: join through the Beach, under your Beach name.")
end

Players.PlayerAdded:Connect(function(player)
    task.spawn(admit, player)
end)
Players.PlayerRemoving:Connect(function(player)
    admitted[player.UserId] = nil
end)

-- Follow renames (and revoked access) for everyone already admitted.
task.spawn(function()
    while true do
        task.wait(REFRESH_S)
        for _, player in ipairs(Players:GetPlayers()) do
            local current = admitted[player.UserId]
            if current then
                local claim = matchingClaim(player)
                if claim and claim.left then
                    -- They pressed Leave on the Beach (or played again from elsewhere): one
                    -- character per person, so this one goes.
                    admitted[player.UserId] = nil
                    player:Kick("You left this world. See you on the beach!")
                elseif not claim or claim.revoked then
                    admitted[player.UserId] = nil
                    player:Kick("Your access to this Beach was withdrawn.")
                elseif claim.name ~= current then
                    admitted[player.UserId] = claim.name
                    setLabel(player, claim.name)
                end
            end
        end
    end
end)

