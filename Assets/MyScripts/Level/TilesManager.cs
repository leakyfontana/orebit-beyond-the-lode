using System.Collections;
using System.Collections.Generic;
using UnityEngine.Tilemaps;
using UnityEngine;

public class TilesManager : MonoBehaviour
{
	public Tilemap traversable_tilemap;
	public Tilemap diggable_tilemap;
	public Dictionary<(int x, int y), GameObject> allBlocks = new Dictionary<(int, int), GameObject>();
	
	private readonly Vector3Int[] neighbourPositions = {Vector3Int.up, Vector3Int.right, Vector3Int.down, Vector3Int.left, Vector3Int.up + Vector3Int.right, Vector3Int.up + Vector3Int.left, Vector3Int.down + Vector3Int.right, Vector3Int.down + Vector3Int.left};
	public bool blockChangedTexture = false;
		
	public string getBlockNameFromAllTiles(int x, int y){
		return allBlocks[(x, y)].GetComponent<BlockData>().object_name;
	}
	
	public bool doesBlockExistAndIsDiggable(int x, int y){
		return (GetComponent<TilesManager>().allBlocks.ContainsKey((x, Mathf.Abs(y))) && allBlocks[(x, Mathf.Abs(y))].GetComponent<BlockData>().isDiggable && !(allBlocks[(x, Mathf.Abs(y))].GetComponent<BlockData>().object_name == "Rock"));
	}

	public bool doesBlockExistAndIsNotDiggable(int x, int y){
		return (GetComponent<TilesManager>().allBlocks.ContainsKey((x, Mathf.Abs(y))) && (allBlocks[(x, Mathf.Abs(y))].GetComponent<BlockData>().isInvincible || allBlocks[(x, Mathf.Abs(y))].GetComponent<BlockData>().object_name == "Rock"));
	}
	
	public void halfwayDigBlock(GameObject block_target, int previous_x, int previous_y, int desired_orientation){
		block_target.GetComponent<BlockAnimation>().updateSpriteBlockHalfwayDug(desired_orientation);
		int x = block_target.GetComponent<BlockData>().map_x;
		int y = block_target.GetComponent<BlockData>().map_y;
		blockChangedTexture = true;
		LevelData.my_map[x][y][0] = 0;
		LevelData.my_map[x][y][1] = 0;
		GetComponent<TilesLoader>().updateTraversableTileData(previous_y, previous_x); //I need to invert the y and the x for some reason? Im not sure why and I'd rather not touch it
	}
	
	public void digBlock(int x, int y){
		blockChangedTexture = false;
		GameObject block_to_destroy = allBlocks[(x, y)];
		Destroy(allBlocks[(x, y)]);
		GetComponent<TilesLoader>().createNewBlock(x, y);
		foreach (Vector3Int pos in neighbourPositions){
			GetComponent<TilesLoader>().updateTraversableTileData(x + pos.x, y + pos.y);
		}
	}
	
	public void digBlock(GameObject block){
		digBlock(block.GetComponent<BlockData>().map_x, block.GetComponent<BlockData>().map_y);
	}
	
	public void instantDigBlock(int x, int y){
		LevelData.my_map[x][y][0] = 0;
		LevelData.my_map[x][y][1] = 0;
		digBlock(x, y);
	}

	public void instantDigBlock(GameObject block){
		if(block.GetComponent<BlockData>().isDiggable){
			instantDigBlock(block.GetComponent<BlockData>().map_x, block.GetComponent<BlockData>().map_y);			
		}
	}
}
