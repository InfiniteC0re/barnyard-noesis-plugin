from collections import namedtuple
from inc_noesis import *

SYMBEntry = namedtuple("SYMBEntry", "id name nameID offset")
AnimChannel = namedtuple("AnimChannel", "bone flags keysCount keysOffset")


def readStringFromOffset(bs: NoeBitStream, offset: int) -> str:
    old_offset = bs.tell()
    bs.seek(offset)
    res = bs.readString()
    bs.seek(old_offset)

    return res


class Tag:
    def __init__(self, bs: NoeBitStream) -> None:
        self.name = None
        self.size = 0
        self.offset = 0

        if bs != None:
            self.read(bs)

    def read(self, bs: NoeBitStream) -> None:
        self.name = noeStrFromBytes(bs.readBytes(4))
        self.size = bs.readUInt()
        self.offset = bs.tell()

    def isIt(self, name) -> bool:
        return self.name == name


class HDRX(Tag):
    def __init__(self, bs: NoeBitStream) -> None:
        super().__init__(bs)


class SECT(Tag):
    def __init__(self, bs: NoeBitStream) -> None:
        super().__init__(bs)
        self.isEncoded = noeStrFromBytes(bs.readBytes(4)) == "BTEC"
        bs.seek(-4, NOESEEK_REL)
        self.bs = NoeBitStream(bs.readBytes(self.size))


class RELC(Tag):
    def __init__(self, bs: NoeBitStream) -> None:
        super().__init__(bs)
        self.count = bs.readUInt()
        self.structures = [(bs.readUShort(), bs.readUShort(),
                            bs.readUInt()) for i in range(self.count)]


class SYMB(Tag):
    def __init__(self, bs: NoeBitStream) -> None:
        super().__init__(bs)
        self.count = bs.readUInt()

        namesOffset = bs.tell() + 12 * self.count
        self.symbols = [SYMBEntry(bs.readShort(), readStringFromOffset(bs, namesOffset + bs.readUInt()), bs.readShort(), bs.readUInt()) for i in range(self.count)]

    def find(self, name: str) -> SYMBEntry:
        for symbol in self.symbols:
            if symbol.name == name:
                return symbol

        return None

class TSFL(Tag):
    def __init__(self) -> None:
        super().__init__(None)

        self.type = None
        self.hdrx = None
        self.sect = None
        self.relc = None
        self.symb = None

        self.check()

    def read(self, bs: NoeBitStream) -> None:
        super().read(bs)

        if self.check():
            self.type = noeStrFromBytes(bs.readBytes(4))

            self.hdrx = HDRX(bs)
            bs.seek(self.hdrx.size, NOESEEK_REL)

            self.sect = SECT(bs)
            if self.sect.isEncoded:
                self.isValid = False
                return False

            self.relc = RELC(bs)
            self.symb = SYMB(bs)

    def check(self) -> bool:
        self.isValid = self.isIt("TSFL")
        return self.isValid


class Keylib(TSFL):
    def __init__(self) -> None:
        super().__init__()
        self.locNum = 0
        self.rotNum = 0

    def read(self, bs: NoeBitStream) -> None:
        super().read(bs)
        sect = self.sect.bs

        sect.seek(0x10)
        self.locNum = sect.readUInt()
        self.rotNum = sect.readUInt()
        sect.seek(0x28)
        locsOffset = sect.readUInt()
        rotsOffset = sect.readUInt()

        sect.seek(locsOffset)
        self.translations = [NoeVec3.fromBytes(sect.readBytes(12)) for i in range(self.locNum)]
        sect.seek(rotsOffset)
        self.rotations = [NoeQuat.fromBytes(sect.readBytes(16)) for i in range(self.rotNum)]


class TMDL:
    def __init__(self, tsfl: TSFL, bs: NoeBitStream) -> None:
        self.isValid = False
        self.isInterior = False
        self.meshes = []

        sect = tsfl.sect.bs
        materialsSymb = tsfl.symb.find("Materials")
        if materialsSymb == None:    
            return

        sect.seek(materialsSymb.offset)
        self.materials = Materials(bs)

        fileHeaderSymb = tsfl.symb.find("FileHeader")
        if fileHeaderSymb == None:
            databaseSymb = tsfl.symb.find("Database")

            if databaseSymb == None:
                return

            sect.seek(databaseSymb.offset)
            count = sect.readUInt()
            if count == 0: 
                return

            sect.seek(sect.readUInt())
            sect.seek(sect.readUInt())

            modelsCount = sect.readUInt()
            if modelsCount == 0: 
                return

            sect.seek(sect.readUInt())
            sect.seek(sect.readUInt() + 0x84)

            meshesCount = sect.readUInt()
            sect.seek(sect.readUInt())
            meshesOffsets = [sect.readUInt() for i in range(meshesCount)]

            for offset in meshesOffsets:
                sect.seek(offset)
                sect.readUInt(); sect.readUInt(); sect.readUInt(); sect.readUInt()
                sect.seek(sect.readUInt())
                sect.readUInt() # some zero

                vertArray = []
                normArray = []
                faceArray = []
                uvArray = []

                faceCount = sect.readUInt()
                vertexCount = sect.readUInt()
                indiceCount = sect.readUInt()
                matName = readStringFromOffset(sect, sect.readUInt())
                vertexesOffset = sect.readUInt()
                facesOffset = sect.readUInt()
                
                bs.seek(vertexesOffset)
                for v in range(vertexCount):
                    vertArray.append(NoeVec3((sect.readFloat(), sect.readFloat(), sect.readFloat())))
                    normArray.append(NoeVec3((sect.readFloat(), sect.readFloat(), sect.readFloat())))
                    sect.seek(12, NOESEEK_REL)
                    uvArray.append(NoeVec3((sect.readFloat(), sect.readFloat(), 0))) # uvs
                
                # reading faces
                sect.seek(facesOffset)
                startDir = -1
                indexCounter = 2
                faceDir = startDir

                faceA = sect.readUShort()
                faceB = sect.readUShort()
                faceC = 0

                while True:
                    faceC = sect.readUShort()
                    indexCounter += 1

                    if faceC == 0xFFFF:
                        indexCounter += 2
                        faceA = sect.readUShort()
                        faceB = sect.readUShort()
                        faceDir = startDir
                    else:
                        faceDir *= -1
                        if faceA != faceB and faceB != faceC and faceC != faceA:
                            if faceDir > 0:
                                faceArray.append(faceA)
                                faceArray.append(faceB)
                                faceArray.append(faceC)
                            else:
                                faceArray.append(faceA)
                                faceArray.append(faceC)
                                faceArray.append(faceB)

                        faceA = faceB
                        faceB = faceC

                    if not sect.tell() < faceCount * 2 + facesOffset:
                        break

                mesh = NoeMesh([], [], "mesh_0", matName)
                mesh.setPositions(vertArray)
                mesh.setNormals(normArray)
                mesh.setIndices(faceArray)
                mesh.setUVs(uvArray)

                self.meshes.append(mesh)
            
            self.isInterior = True
            self.isValid = True
            return

        sect.seek(fileHeaderSymb.offset)
        self.fileHeader = FileHeader(bs)

        skeletonHeaderSymb = tsfl.symb.find("SkeletonHeader")
        if skeletonHeaderSymb != None:    
            sect.seek(skeletonHeaderSymb.offset)
            self.tklName = bs.readString()

        skeletonSymb = tsfl.symb.find("Skeleton")
        if skeletonSymb != None:    
            sect.seek(skeletonSymb.offset)
            self.skeleton = Skeleton(bs)

        # loading all meshes of LOD0
        if self.isInterior == False:
            for i in range(32):
                symb = tsfl.symb.find("LOD0_Mesh_" + str(i))
                
                if symb == None:
                    break
                
                sect.seek(symb.offset)
                lod_meshInfoCount = sect.readUInt()
                faceCount = sect.readUInt()
                vertexCount = sect.readUInt()
                matName = readStringFromOffset(sect, sect.readUInt())
                sect.seek(sect.readUInt())
                meshInfos = [{ "unknown": sect.readUInt(), "vertexCount": sect.readUInt(), "faceCount": sect.readUInt(), "indiceCount": sect.readUInt(), "indiceOffset": sect.readUInt(), "vertexOffset": sect.readUInt(), "faceOffset": sect.readUInt(), "zero": sect.readUInt(), "hash": sect.readUInt(), "unkVec": NoeVec4((sect.readFloat(), sect.readFloat(), sect.readFloat(), sect.readFloat())) } for i in range(lod_meshInfoCount)]

                for k in range(lod_meshInfoCount):
                    mesh = NoeMesh([], [], "mesh_0", matName)
                    indiceArr = []
                    vertArray = []
                    faceArray = []
                    normArray = []
                    weightArr = []
                    uvArray = []

                    sect.seek(meshInfos[k]["indiceOffset"])
                    for v in range(meshInfos[k]["indiceCount"]):
                        indiceArr.append(sect.readUInt())

                    sect.seek(meshInfos[0]["vertexOffset"])
                    for v in range(meshInfos[k]["vertexCount"]):
                        vertArray.append(NoeVec3((sect.readFloat(), sect.readFloat(), sect.readFloat())))
                        normArray.append(NoeVec3((sect.readFloat(), sect.readFloat(), sect.readFloat())))
                        
                        weights = [sect.readUByte() / 255 for j in range(4)]
                        bones = [indiceArr[int((sect.readUByte() / 3) % len(indiceArr))] for j in range(4)]

                        vertWeight = NoeVertWeight(bones, weights)
                        uvArray.append(NoeVec3((sect.readFloat(), sect.readFloat(), 0))) # uvs
                        weightArr.append(vertWeight)

                    # reading faces
                    sect.seek(meshInfos[k]["faceOffset"])
                    startDir = -1
                    indexCounter = 2
                    faceDir = startDir

                    faceA = sect.readUShort()
                    faceB = sect.readUShort()
                    faceC = 0

                    while True:
                        faceC = sect.readUShort()
                        indexCounter += 1

                        if faceC == 0xFFFF:
                            indexCounter += 2
                            faceA = sect.readUShort()
                            faceB = sect.readUShort()
                            faceDir = startDir
                        else:
                            faceDir *= -1
                            if faceA != faceB and faceB != faceC and faceC != faceA:
                                if faceDir > 0:
                                    faceArray.append(faceA)
                                    faceArray.append(faceB)
                                    faceArray.append(faceC)
                                else:
                                    faceArray.append(faceA)
                                    faceArray.append(faceC)
                                    faceArray.append(faceB)

                            faceA = faceB
                            faceB = faceC

                        if not sect.tell() < meshInfos[k]["faceCount"] * 2 + meshInfos[k]["faceOffset"]:
                            break

                    mesh.setPositions(vertArray)
                    mesh.setNormals(normArray)
                    mesh.setIndices(faceArray)
                    mesh.setUVs(uvArray)
                    mesh.setWeights(weightArr)

                    self.meshes.append(mesh)

        self.isValid = True


class FileHeader:
    def __init__(self, bs: NoeBitStream) -> None:
        self.signature = noeStrFromBytes(bs.readBytes(4))
        self.zero1 = bs.readUInt()
        self.unk = bs.readUInt()
        self.zero2 = bs.readUInt()
        self.isValid = self.signature == "TMDL"


class Skeleton:
    def __init__(self, bs: NoeBitStream) -> None:
        self.nodesCount = bs.readUInt()
        self.animationsCount = bs.readUShort()
        bs.seek(0x2E, NOESEEK_REL)
        self.firstBoneOffset = bs.readUInt()
        self.animationOffset = bs.readUInt()
        self.fallbackQuats = []
        self.fallbackTranses = []
        self.bones = []
        self.anims = []

        for i in range(self.nodesCount):
            boneOffset = self.firstBoneOffset + 0xC0 * i
            bs.seek(boneOffset)

            rotation = NoeQuat.fromBytes(bs.readBytes(16))
            transform = NoeMat44.toMat43(NoeMat44.fromBytes(bs.readBytes(64)))
            transform_inv = NoeMat44.fromBytes(bs.readBytes(64))
            name = noeStrFromBytes(bs.readBytes(bs.readUByte()))
            bs.seek(31 - len(name), NOESEEK_REL)
            parentId = bs.readShort()
            unk = bs.readUShort()
            fallbackTrans = NoeVec3.fromBytes(bs.readBytes(12))

            self.fallbackQuats.append(rotation)
            self.fallbackTranses.append(fallbackTrans)

            bone = NoeBone(i, name, transform, None, parentId)
            self.bones.append(bone)

    def loadAnimations(self, bs: NoeBitStream, keylib: Keylib) -> None:
        for i in range(self.animationsCount):
            animOffset = self.animationOffset + 0x30 * i
            bs.seek(animOffset)

            name = noeStrFromBytes(bs.readBytes(bs.readUByte()))
            bs.seek(animOffset + 0x20)
            flag = bs.readUInt()
            channelsCount = bs.readUInt()
            duration = bs.readFloat()
            channelsOffset = bs.readUInt()
            kfBones = []

            bs.seek(channelsOffset)
            for k in range(channelsCount):
                # bone, flags, keysCount, keysOffset, keys
                channel = AnimChannel(self.bones[k], bs.readUShort(), bs.readUShort(), bs.readUInt())
                boneChannel = NoeKeyFramedBone(k)
                boneKeys_rot = []
                boneKeys_loc = []
                
                channelMode = (channel.flags >> 8 * 0) & 0xff
                keyBytesCount = (channel.flags >> 8 * 1) & 0xff;
                backOffset = bs.tell()

                # skip
                if channelMode == 2:
                    continue

                bs.seek(channel.keysOffset)
                for j in range(channel.keysCount):
                    if keyBytesCount >= 4:
                        time = bs.readUShort() / 65535 * duration
                        rotIndex = bs.readUShort()

                        mat = NoeQuat.toMat43(keylib.rotations[rotIndex])

                        if channelMode == 0:
                            mat = mat.translate(self.fallbackTranses[k])
                        elif channelMode == 1:
                            locIndex = bs.readUShort()
                            mat = mat.translate(keylib.translations[locIndex])
                        
                        mat = mat.inverse()

                        if channelMode in (3, 1):
                            kfValue = NoeKeyFramedValue(time, mat[3] * -1)
                            boneKeys_loc.append(kfValue)

                        if channelMode in (0, 1):
                            kfValue = NoeKeyFramedValue(time, mat.toQuat())
                            boneKeys_rot.append(kfValue)

                bs.seek(backOffset)

                boneChannel.setTranslation(boneKeys_loc)
                boneChannel.setRotation(boneKeys_rot)
                kfBones.append(boneChannel)

            anim = NoeKeyFramedAnim(name, self.bones, kfBones, 30)
            self.anims.append(anim)


class Materials:
    def __init__(self, bs: NoeBitStream) -> None:
        self.zero1 = bs.readUInt()
        self.zero2 = bs.readUInt()
        self.matCount = bs.readUInt()
        self.matsSize = bs.readUInt()
        self.firstMatOffset = bs.tell()
        self.list = []

        for i in range(self.matCount):
            offset = self.firstMatOffset + i * 0x128
            bs.seek(offset)

            matName = bs.readString()
            texName = readStringFromOffset(bs, offset + 0x68)
            self.list.append((matName, texName))
    
    def find(self, name: str) -> tuple:
        for mat in self.list:
            if mat[0] == name:
                return mat

        return None


def loadMaterial(name, path, texList, matList):
    tex = rapi.loadExternalTex(path.replace(".tga", ".png"))
    
    if tex != None:
        tex.name = name
        texList.append(tex)
        matList.append(NoeMaterial(name, name))


def registerNoesisTypes():
    handle = noesis.register("Barnyard TMDL", ".trb")
    noesis.setHandlerTypeCheck(handle, trbCheckType)
    noesis.setHandlerLoadModel(handle, trbLoadModel)
    # noesis.logPopup()

    return True


tsfl = TSFL()
tmdl = None


def trbCheckType(data):
    global tsfl
    global tmdl

    bs = NoeBitStream(data)
    tsfl.read(bs)

    if tsfl.isValid and not tsfl.sect.isEncoded:
        tmdl = TMDL(tsfl, tsfl.sect.bs)

        return tmdl.isValid
    else:
        return False


def trbLoadModel(data, mdlList):
    # add the model to scene
    mdl = NoeModel(tmdl.meshes, [])

    # load materials
    texList = []
    matList = []
    for mat in tmdl.materials.list:
        loadMaterial(mat[0], mat[1], texList, matList)

    if not tmdl.isInterior:
        # load the key library
        tkl_file = open(rapi.getDirForFilePath(rapi.getInputName()) + tmdl.tklName + ".tkl", "rb")
        tkl_bs = NoeBitStream(tkl_file.read())

        keylib = Keylib()
        keylib.read(tkl_bs)

        # initalize animations
        tmdl.skeleton.loadAnimations(tsfl.sect.bs, keylib)

        mdl.setBones(tmdl.skeleton.bones)
        mdl.setAnims(tmdl.skeleton.anims)

    rapi.processCommands("-rotate 90 0 0")
    rapi.processCommands("-scale 100")
    rapi.processCommands("-combinemeshes")
    rapi.processCommands("-fbxmultitake")
    rapi.processCommands("-fbxframerate 60")
    mdl.setModelMaterials(NoeModelMaterials(texList, matList))
    mdlList.append(mdl)
    
    return True
