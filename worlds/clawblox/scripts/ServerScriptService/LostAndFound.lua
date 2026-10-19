-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
-- Lost and found for the ClawBlox world (the keeper's idea, 10-18): the boulder and the ring are the
-- toys people carry about, and mesa-island never brings back anything that falls off the island. When
-- either falls below the island, put it back beside the spawn point, where everyone arrives.
-- Ours, laid over the assembled world by scripts/clawblox_world.py; mesa-island's files are untouched.

local Workspace = game:GetService("Workspace")

local FALLEN_Y = -20                     -- below this, it has fallen off the island
local SPAWN = Vector3.new(0, 0, 0)       -- mesa-island's PLAYER_SPAWN_POSITION is (0, 5, 0)
local HOMES = {
    Rock_1 = SPAWN + Vector3.new(5, 3.1, 0),     -- the boulder, a few steps east of the spawn
    Ring_1 = SPAWN + Vector3.new(-5, 0.3, 0),    -- the ring, a few steps west
}

task.spawn(function()
    while true do
        task.wait(1)
        for name, home in pairs(HOMES) do
            local part = Workspace:FindFirstChild(name)
            if part and part:IsA("BasePart") and part.Position.Y < FALLEN_Y then
                part.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
                part.AssemblyAngularVelocity = Vector3.new(0, 0, 0)
                part.Position = home
                print("[LostAndFound] " .. name .. " fell off the island and is back by the spawn")
            end
        end
    end
end)
